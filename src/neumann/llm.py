"""제품 LLM 호출 층 (E3 소유).

모든 호출은 한 경로다: **JSON 스키마 요청 → 로컬 재검증**. 실패·시간 초과·스키마 위반은 예외 대신
`LLMResult(ok=False, error=...)`로 돌려주고, 호출부가 그 단계만 비상 규칙 경로로 돌린다.

provider
- `openai`: OpenAI Responses API. 제품 모델 기본값은 `gpt-6.1-sol`(설정 NEUMANN_LLM_MODEL). `temperature`는 보내지 않는다(최신 추론 모델이 거부).
  추론 강도(`reasoning.effort`)는 호출마다 정한다. 키는 설정의 SecretStr에서만 꺼낸다.
- `mock`: 결정적 응답. 과제(task)별 응답 함수(규칙 결과를 LLM 응답 모양으로 만든 것)나 대본(scripted)으로 답한다.
  mock 응답도 같은 로컬 재검증을 거친다.
- `off`: 끈 상태. 모든 호출이 `disabled` 실패로 돌아간다(비상 경로 확인용).

로그·예외 메시지에 요청 헤더, 키, 설정 객체 전체를 남기지 않는다. 실패 사유는 짧은 분류 문자열(`error`)과
비밀값 없는 한 줄 설명(`detail`)뿐이다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import jsonschema

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-6.1-sol"
MOCK_MODEL = "mock-deterministic-v1"
EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh"})

# 호출(task)별 기본값. 설정 키로 덮어쓴다(`llm_effort_<task>` 속성 또는 NEUMANN_LLM_EFFORT_<TASK> 환경변수).
# v1 단계(적합성·예상 심사평·체크리스트·2차 검증)의 상한은 실측 지연(E3-L1a·b·c 보고서: 5~7s·12.5s·16.4s·12.4s)의 약 5배.
TASK_DEFAULTS: dict[str, dict[str, Any]] = {
    "fitness": {"effort": "low", "timeout_s": 30.0},
    "query_axes": {"effort": "low", "timeout_s": 45.0},
    "extract_issues": {"effort": "low", "timeout_s": 90.0},
    "synthesize_cards": {"effort": "medium", "timeout_s": 120.0},
    "expected_review": {"effort": "medium", "timeout_s": 90.0},
    "checklist": {"effort": "medium", "timeout_s": 90.0},
    "semantic_validate": {"effort": "medium", "timeout_s": 90.0},
}

# 실패 분류. 호출부는 reason()을 StageStatus.detail에 옮긴다.
# detail에는 분류·HTTP 코드·상한 같은 짧은 사실만 둔다. 예외 원문·API 오류 문구(키 조각이 들어갈 수 있다)·
# 경로·요청 정보는 결과에도 로그에도 싣지 않는다(SEC-1 S-04).
FAIL_TIMEOUT = "timeout"
FAIL_API = "api_error"
FAIL_JSON = "json_invalid"
FAIL_SCHEMA = "schema_invalid"
FAIL_EMPTY = "empty_output"
FAIL_INCOMPLETE = "incomplete"
FAIL_DISABLED = "disabled"
FAIL_CONFIG = "config_error"

FAIL_LABELS: dict[str, str] = {
    FAIL_TIMEOUT: "시간 초과",
    FAIL_API: "API 오류",
    FAIL_JSON: "응답 JSON 깨짐",
    FAIL_SCHEMA: "응답 스키마 위반",
    FAIL_EMPTY: "빈 응답",
    FAIL_INCOMPLETE: "응답 미완료",
    FAIL_DISABLED: "LLM 꺼짐",
    FAIL_CONFIG: "설정 오류",
}


@dataclass(frozen=True)
class LLMCall:
    """한 번의 구조화 호출. payload는 JSON으로 직렬화되어 사용자 입력이 된다."""

    task: str
    instructions: str
    payload: dict[str, Any]
    schema: dict[str, Any]
    schema_name: str
    effort: str | None = None
    timeout_s: float | None = None
    max_output_tokens: int | None = None

    def input_text(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))


@dataclass
class LLMResult:
    ok: bool
    data: dict[str, Any] | None
    provider: str
    model: str
    task: str
    effort: str | None = None
    latency_s: float = 0.0
    error: str | None = None
    detail: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    attempts: int = 1

    @property
    def generator(self) -> str:
        """결과를 만든 쪽(정직 표기). models.Generator 값과 같은 문자열."""
        return generator_for(self.provider)

    def reason(self) -> str:
        """StageStatus.detail용 사용자 문구 한 줄. 분류 코드와 짧은 사실만(예외 원문·API 문구 없음)."""
        if self.ok:
            return f"{self.provider}:{self.model} ok {self.latency_s:.1f}s"
        label = FAIL_LABELS.get(self.error or "", "호출 실패")
        extra = f", {self.detail}" if self.detail else ""
        return f"{self.provider}:{self.model} 호출 실패({label}{extra}) [{self.error}]"


# provider 이름 → 생성 주체(models.Generator 값). 여기 없는 이름은 추정하지 않는다(provider_generator가 거부).
PROVIDER_GENERATOR: dict[str, str] = {"openai": "astra", "mock": "mock", "off": "rule"}


def generator_for(provider: str) -> str:
    return {"openai": "astra", "mock": "mock"}.get(provider, "rule")


def provider_generator(provider: Any) -> str:
    """provider 객체의 생성 주체. `generator` 속성 → 이름 대응(openai→astra, mock→mock, off→rule).

    둘 다 없거나 모르는 값이면 ValueError. 무엇이 호출됐는지 모르는 provider를 astra로 적지 않는다(추정 금지).
    """
    gen = getattr(provider, "generator", None)
    if gen is None:
        gen = PROVIDER_GENERATOR.get(str(getattr(provider, "name", "") or "").lower())
    if gen not in ("astra", "mock", "rule"):
        name = getattr(provider, "name", None) or type(provider).__name__
        raise ValueError(f"provider {name!r}의 생성 주체를 알 수 없다(generator 속성 없음, 이름 대응 없음)")
    return str(gen)


class LLMProvider(Protocol):
    name: str
    model: str

    def complete_json(self, call: LLMCall) -> LLMResult: ...


# ── 로컬 재검증 ──────────────────────────────────────────────────────────


def validate_output(text: str | None, schema: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """모델 출력 문자열 → (data, error, detail). 스키마를 로컬에서 다시 검사한다."""
    if text is None or not text.strip():
        return None, FAIL_EMPTY, "빈 출력"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, FAIL_JSON, f"위치 {exc.pos}"
    if not isinstance(data, dict):
        return None, FAIL_SCHEMA, "최상위가 객체가 아니다"
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        # 오류 메시지는 모델 출력 값을 담으므로 싣지 않는다. 위치(스키마 경로)와 규칙 이름만.
        first = errors[0]
        path = "/".join(str(p) for p in first.absolute_path) or "(root)"
        return None, FAIL_SCHEMA, f"{len(errors)}건, 첫 오류 {path} ({first.validator})"
    return data, None, None


def check_strict_schema(schema: dict[str, Any], path: str = "$") -> list[str]:
    """OpenAI strict 모드 요건 검사(테스트용): 모든 객체는 additionalProperties=false이고 모든 속성이 required."""
    problems: list[str] = []
    types = schema.get("type")
    types = types if isinstance(types, list) else [types]
    if "object" in types:
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is not False:
            problems.append(f"{path}: additionalProperties가 false가 아니다")
        if sorted(schema.get("required", [])) != sorted(props):
            problems.append(f"{path}: required가 properties 전부가 아니다")
        for name, sub in props.items():
            problems.extend(check_strict_schema(sub, f"{path}.{name}"))
    if "array" in types and isinstance(schema.get("items"), dict):
        problems.extend(check_strict_schema(schema["items"], f"{path}[]"))
    for key in ("anyOf",):
        for i, sub in enumerate(schema.get(key, [])):
            problems.extend(check_strict_schema(sub, f"{path}.{key}[{i}]"))
    return problems


# ── OpenAI ───────────────────────────────────────────────────────────────


class OpenAIProvider:
    """OpenAI Responses API. 스키마는 strict json_schema로 보내고, 받은 뒤 로컬에서 다시 검사한다."""

    name = "openai"

    @property
    def generator(self) -> str:
        """이 provider가 만든 결과의 생성 주체(파이프라인 어댑터가 읽는다). 이름 대응을 따른다."""
        return PROVIDER_GENERATOR[self.name]

    def __init__(
        self,
        *,
        api_key: Any,
        model: str,
        default_timeout_s: float = 60.0,
        client: Any | None = None,
        max_attempts: int = 2,
    ) -> None:
        self.model = model
        self.default_timeout_s = default_timeout_s
        self.max_attempts = max(1, max_attempts)
        self._config_error: str | None = None
        if not model:
            self._config_error = "NEUMANN_LLM_MODEL이 비어 있다"
        self._client = client
        if self._client is None and self._config_error is None:
            key = _secret_value(api_key)
            if not key:
                self._config_error = "OPENAI_API_KEY가 없다"
            elif not _live_llm_allowed():
                # SEC-3: 실제 클라이언트는 허용 플래그가 있을 때만 만든다(직접 생성 경로도 막는다)
                self._config_error = "실제 호출 잠김(NEUMANN_LIVE_LLM_OK 없음)"
            else:
                from openai import OpenAI

                # SDK 재시도는 끄고(시간 초과까지 재시도하면 상한이 두 배가 된다) 아래에서 직접 한 번만 다시 한다.
                self._client = OpenAI(api_key=key, max_retries=0, timeout=default_timeout_s)

    def complete_json(self, call: LLMCall) -> LLMResult:
        effort = call.effort
        timeout = call.timeout_s or self.default_timeout_s
        base = {"provider": self.name, "model": self.model or "(empty)", "task": call.task, "effort": effort}
        if self._config_error:
            return LLMResult(ok=False, data=None, error=FAIL_CONFIG, detail=self._config_error, **base)

        import openai

        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": call.instructions,
            "input": call.input_text(),
            "text": {
                "format": {"type": "json_schema", "name": call.schema_name, "schema": call.schema, "strict": True}
            },
            "store": False,
        }
        if effort:
            kwargs["reasoning"] = {"effort": effort}
        if call.max_output_tokens:
            kwargs["max_output_tokens"] = call.max_output_tokens

        t0 = time.perf_counter()
        attempts = 0
        while True:
            attempts += 1
            remaining = timeout - (time.perf_counter() - t0)
            try:
                resp = self._client.with_options(timeout=max(1.0, remaining)).responses.create(**kwargs)
                break
            except openai.APITimeoutError:
                return self._fail(base, t0, attempts, FAIL_TIMEOUT, f"{timeout:.0f}s 상한")
            except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError) as exc:
                elapsed = time.perf_counter() - t0
                if attempts < self.max_attempts and elapsed < timeout / 2:
                    time.sleep(min(2.0 * attempts, 5.0))
                    continue
                return self._fail(base, t0, attempts, FAIL_API, _api_error_facts(exc), exc)
            except openai.APIStatusError as exc:
                return self._fail(base, t0, attempts, FAIL_API, _api_error_facts(exc), exc)
            except Exception as exc:  # noqa: BLE001 — 어떤 실패든 비상 경로로 넘긴다
                return self._fail(base, t0, attempts, FAIL_API, type(exc).__name__, exc)

        latency = time.perf_counter() - t0
        usage = _usage(resp)
        status = getattr(resp, "status", None)
        if status and status != "completed":
            why = getattr(getattr(resp, "incomplete_details", None), "reason", None)
            facts = f"status={_safe_token(status)}" + (f" {_safe_token(why)}" if why else "")
            return LLMResult(
                ok=False, data=None, error=FAIL_INCOMPLETE, detail=facts,
                latency_s=latency, usage=usage, attempts=attempts, **base,
            )
        data, err, detail = validate_output(getattr(resp, "output_text", None), call.schema)
        if err:
            return LLMResult(ok=False, data=None, error=err, detail=detail, latency_s=latency, usage=usage, attempts=attempts, **base)
        return LLMResult(ok=True, data=data, latency_s=latency, usage=usage, attempts=attempts, **base)

    def _fail(
        self, base: dict[str, Any], t0: float, attempts: int, error: str, detail: str, exc: BaseException | None = None
    ) -> LLMResult:
        latency = time.perf_counter() - t0
        # 로그에도 API 오류 문구(키 조각이 들어갈 수 있다)·요청 본문은 남기지 않는다. 분류·코드·요청 id만.
        request_id = _safe_token(getattr(exc, "request_id", None)) if exc is not None else None
        log.warning(
            "LLM 호출 실패 task=%s error=%s detail=%s exc=%s request_id=%s",
            base["task"], error, detail, type(exc).__name__ if exc is not None else None, request_id,
        )
        return LLMResult(ok=False, data=None, error=error, detail=detail, latency_s=latency, attempts=attempts, **base)


def _secret_value(value: Any) -> str:
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    return getter() if callable(getter) else str(value)


_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def _safe_token(value: Any) -> str | None:
    """짧은 식별자(오류 코드·상태·요청 id)만 통과시킨다. 문장·경로·키 모양은 버린다."""
    if value is None:
        return None
    s = str(value)
    if not _TOKEN_RE.match(s) or s.lower().startswith(("sk-", "sk_")):
        return "?"
    return s


def _api_error_facts(exc: Any) -> str:
    """API 오류의 공개해도 되는 사실: 예외 종류, HTTP 코드, 오류 코드(예 invalid_api_key). 메시지 원문은 버린다."""
    parts = [type(exc).__name__]
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        parts.append(f"HTTP {code}")
    body = getattr(exc, "body", None)
    err = body.get("error", body) if isinstance(body, dict) else None
    err_code = err.get("code") if isinstance(err, dict) else None
    if err_code:
        parts.append(str(_safe_token(err_code)))
    return " ".join(parts)


def _usage(resp: Any) -> dict[str, int]:
    usage = getattr(resp, "usage", None)
    out: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        val = getattr(usage, key, None)
        if isinstance(val, int):
            out[key] = val
    details = getattr(usage, "output_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None)
    if isinstance(reasoning, int):
        out["reasoning_tokens"] = reasoning
    return out


# ── mock · off ───────────────────────────────────────────────────────────

Responder = Callable[[LLMCall], dict[str, Any]]


class MockProvider:
    """결정적 가짜 provider. 응답도 같은 로컬 재검증을 거친다.

    - responders: task → 응답 함수(보통 규칙 결과를 LLM 응답 모양으로 만든 것)
    - scripted: task → 응답 목록(차례로 꺼냄). 딕셔너리 대신 문자열을 넣으면 원문 그대로 검증한다(깨진 JSON 시험용)
    - fail: task → 실패 분류(timeout, api_error …). 강제 실패 시험용
    """

    name = "mock"

    @property
    def generator(self) -> str:
        # 이름을 따른다: 이름만 openai로 바꾼 시험용 하위 클래스는 LLMResult.generator와 같게 astra가 된다.
        return PROVIDER_GENERATOR.get(self.name, "mock")

    def __init__(
        self,
        responders: dict[str, Responder] | None = None,
        *,
        scripted: dict[str, list[Any]] | None = None,
        fail: dict[str, str] | None = None,
        model: str = MOCK_MODEL,
    ) -> None:
        self.model = model
        self.responders = dict(responders or {})
        self.scripted = {k: list(v) for k, v in (scripted or {}).items()}
        self.fail = dict(fail or {})
        self.calls: list[LLMCall] = []

    def complete_json(self, call: LLMCall) -> LLMResult:
        self.calls.append(call)
        base = {"provider": self.name, "model": self.model, "task": call.task, "effort": call.effort}
        if call.task in self.fail:
            return LLMResult(ok=False, data=None, error=self.fail[call.task], detail="mock 강제 실패", **base)
        if self.scripted.get(call.task):
            item = self.scripted[call.task].pop(0)
            raw = item(call) if callable(item) else item
        elif call.task in self.responders:
            raw = self.responders[call.task](call)
        else:
            return LLMResult(ok=False, data=None, error=FAIL_CONFIG, detail=f"mock 응답 없음: {call.task}", **base)
        text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        data, err, detail = validate_output(text, call.schema)
        if err:
            return LLMResult(ok=False, data=None, error=err, detail=detail, **base)
        return LLMResult(ok=True, data=data, **base)


class DisabledProvider:
    """끈 상태. 모든 호출이 실패로 돌아가 호출부가 비상 경로로 간다."""

    name = "off"
    generator = "rule"  # 꺼진 provider로 만든 결과는 모두 규칙 경로다

    def __init__(self, reason: str = "LLM provider 꺼짐") -> None:
        self.model = "none"
        self.reason = reason

    def complete_json(self, call: LLMCall) -> LLMResult:
        return LLMResult(
            ok=False, data=None, provider=self.name, model=self.model, task=call.task,
            effort=call.effort, error=FAIL_DISABLED, detail=self.reason,
        )


# ── 설정 → provider ──────────────────────────────────────────────────────


def setting(settings: Any, attr: str, env: str, default: Any = None) -> Any:
    """설정 객체 속성 → 환경변수 → 기본값. (config.py에 키가 아직 없을 때를 위한 우회)"""
    val = getattr(settings, attr, None) if settings is not None else None
    if val in (None, ""):
        val = os.environ.get(env)
    return default if val in (None, "") else val


def task_options(task: str, settings: Any = None) -> dict[str, Any]:
    """호출별 추론 강도·시간 상한. 설정 키: llm_effort_<task> / NEUMANN_LLM_EFFORT_<TASK>,
    llm_timeout_<task>_s / NEUMANN_LLM_TIMEOUT_<TASK>_S. 없으면 TASK_DEFAULTS, 그다음 NEUMANN_LLM_TIMEOUT_S."""
    defaults = TASK_DEFAULTS.get(task, {"effort": "low", "timeout_s": 60.0})
    effort = str(setting(settings, f"llm_effort_{task}", f"NEUMANN_LLM_EFFORT_{task.upper()}", defaults["effort"]))
    if effort not in EFFORTS:
        log.warning("알 수 없는 추론 강도 %r (task=%s) → %s", effort, task, defaults["effort"])
        effort = defaults["effort"]
    timeout = setting(settings, f"llm_timeout_{task}_s", f"NEUMANN_LLM_TIMEOUT_{task.upper()}_S", None)
    if timeout is None:
        timeout = defaults["timeout_s"]
    return {"effort": effort, "timeout_s": float(timeout)}


def _live_llm_allowed() -> bool:
    try:
        from neumann.config import live_llm_allowed
    except Exception:  # noqa: BLE001 - 설정 모듈을 못 읽으면 닫힌 쪽
        return False
    return live_llm_allowed()


def make_llm(settings: Any = None, provider: str | None = None) -> LLMProvider:
    """설정에서 provider를 만든다. provider 인자가 있으면 설정보다 우선한다.

    모델명이 비었거나 키가 없으면 조용히 끄지 않는다: 호출마다 config_error 실패를 돌려 status에 드러난다.
    """
    name = (provider or setting(settings, "llm_provider", "NEUMANN_LLM_PROVIDER", "mock") or "mock").lower()
    if name == "openai" and not _live_llm_allowed():
        # SEC-3: 허용 플래그 없는 프로세스(에이전트·worktree·테스트)는 설정이 openai여도 실제 호출을 하지 않는다.
        # 결과의 generator가 mock이 되므로 화면·결과에 그대로 드러난다.
        log.warning("provider=openai 요청이지만 NEUMANN_LIVE_LLM_OK가 없어 mock으로 강등한다")
        name = "mock"
    if name == "openai":
        model = str(setting(settings, "llm_model", "NEUMANN_LLM_MODEL", DEFAULT_MODEL))
        key = getattr(settings, "openai_api_key", None) if settings is not None else None
        if key is None or not _secret_value(key):
            key = os.environ.get("OPENAI_API_KEY")
        timeout = float(setting(settings, "llm_timeout_s", "NEUMANN_LLM_TIMEOUT_S", 60.0))
        return OpenAIProvider(api_key=key, model=model, default_timeout_s=timeout)
    if name in ("mock", "rules"):
        from neumann.analyze.mock_responders import default_responders

        return MockProvider(default_responders())
    if name in ("off", "none", "disabled"):
        return DisabledProvider(f"provider={name}")
    return DisabledProvider(f"알 수 없는 provider {name!r}")


__all__ = [
    "DEFAULT_MODEL",
    "DisabledProvider",
    "LLMCall",
    "LLMProvider",
    "LLMResult",
    "MockProvider",
    "OpenAIProvider",
    "PROVIDER_GENERATOR",
    "TASK_DEFAULTS",
    "check_strict_schema",
    "setting",
    "generator_for",
    "make_llm",
    "provider_generator",
    "task_options",
    "validate_output",
]
