"""일반 LLM 기준선(04_평가_명세 §0.2 주 기준선): 같은 OpenAI 모델에 계획서만 넣고 위험 3개를 묻는다.

사전 고정(2026-09-30):
- 모델: 제품과 같은 모델(설정 NEUMANN_LLM_MODEL, 기본 `gpt-6.1-sol`), OpenAI Responses API. 코퍼스·검색·택소노미는 주지 않는다.
- 프롬프트: `eval/prompts/baseline_llm.txt` 원문 그대로(공개). 사용자 입력은 계획서 본문 하나뿐.
  핵심 문장 "이 연구계획서가 심사에서 받을 위험 3개를 구체적으로"를 그대로 담는다.
- 추론 강도 medium(제품 카드 합성 단계 E3 `synthesize_cards` 기본값과 같다). temperature는 보내지 않는다.
- 출력: strict JSON 스키마(위험 정확히 3개, 제목·설명). 받은 뒤 로컬에서 다시 검사한다.
  형식 위반(개수·빈 칸·설명 2문장 초과)이면 한 번 더 부른다(최대 2회). 그래도 2문장을 넘으면 앞 2문장으로 자르고 표시한다.
- 캐시: 키 = sha256(provider|요청 모델|추론 강도|프롬프트 버전|계획서 sha256). 같은 계획서는 다시 부르지 않는다.
  셔플 조건(논문 i의 심사평으로 판정, 계획서는 j)은 계획서 j의 결과를 그대로 쓴다(입력이 같다).
- 기록: 요청 모델과 **응답이 돌려준 실제 모델 id**, 지연, 토큰 사용량, 시도 수. 키·헤더는 기록하지 않는다.

실행:
    python -m eval.baseline_llm --provider openai --limit 3 --conditions real   # 3편만 확인
    python -m eval.baseline_llm --provider openai                               # 30편 × (진짜·셔플)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from eval.backtest_common import eval_dir, read_json, read_jsonl, utf8_stdio, write_jsonl
from eval.backtest_riskset import K, MAX_SENTENCES, count_sentences, make_risk, make_riskset

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "baseline_llm.txt"
SYSTEM = "baseline_llm"
DEFAULT_MODEL = "gpt-6.1-sol"
EFFORT = "medium"
TIMEOUT_S = 120.0
MAX_ATTEMPTS = 2
MAX_TITLE_CHARS = 80

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["risks"],
    "properties": {
        "risks": {
            "type": "array",
            "minItems": K,
            "maxItems": K,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "description"],
                "properties": {"title": {"type": "string"}, "description": {"type": "string"}},
            },
        }
    },
}


def load_prompt(path: Path = PROMPT_PATH) -> tuple[str, str]:
    """(프롬프트 원문, 버전 = 원문 sha256 앞 16자). 줄바꿈은 LF로 읽는다."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def output_problems(data: Any) -> list[str]:
    """로컬 재검사. 빈 목록이면 형식 통과."""
    if not isinstance(data, dict) or not isinstance(data.get("risks"), list):
        return ["risks 배열 없음"]
    risks = data["risks"]
    p = []
    if len(risks) != K:
        p.append(f"위험 {len(risks)}개(정확히 {K}개여야 한다)")
    for i, r in enumerate(risks, 1):
        if not isinstance(r, dict):
            p.append(f"{i}: 객체 아님")
            continue
        t, d = str(r.get("title", "")).strip(), str(r.get("description", "")).strip()
        if not t or not d:
            p.append(f"{i}: 빈 제목·설명")
        if len(t) > MAX_TITLE_CHARS:
            p.append(f"{i}: 제목 {len(t)}자 > {MAX_TITLE_CHARS}")
        n = count_sentences(d)
        if n > MAX_SENTENCES:
            p.append(f"{i}: 설명 {n}문장 > {MAX_SENTENCES}")
    return p


class Provider(Protocol):
    name: str
    model: str
    effort: str

    def generate(self, instructions: str, plan_text: str) -> dict[str, Any]: ...


class OpenAIBaseline:
    """OpenAI Responses API. 실패는 예외 대신 {"ok": False, "error": ...}로 돌려준다(키·헤더는 담지 않는다)."""

    name = "openai"

    def __init__(self, model: str | None = None, effort: str = EFFORT, timeout_s: float = TIMEOUT_S, client: Any = None) -> None:
        self.model = model or os.environ.get("NEUMANN_LLM_MODEL") or DEFAULT_MODEL
        self.effort = effort
        self.timeout_s = timeout_s
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:  # SEC-3: 실제 호출은 NEUMANN_LIVE_LLM_OK가 있을 때만
                from neumann.config import live_llm_allowed

                allowed = live_llm_allowed()
            except Exception:  # noqa: BLE001
                allowed = False
            if not allowed:
                raise RuntimeError("실제 호출 잠김(NEUMANN_LIVE_LLM_OK 없음)")
            from openai import OpenAI

            key = None
            try:
                from neumann.config import get_settings

                s = get_settings().openai_api_key
                key = s.get_secret_value() if s is not None else None
            except Exception:  # noqa: BLE001
                key = None
            key = key or os.environ.get("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("OPENAI_API_KEY가 없다")
            self._client = OpenAI(api_key=key, max_retries=1, timeout=self.timeout_s)
        return self._client

    def generate(self, instructions: str, plan_text: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            resp = self._get_client().responses.create(
                model=self.model,
                instructions=instructions,
                input=plan_text,
                reasoning={"effort": self.effort},
                text={"format": {"type": "json_schema", "name": "baseline_risks", "schema": SCHEMA, "strict": True}},
                store=False,
            )
        except Exception as exc:  # noqa: BLE001 — 분류만 남긴다
            code = getattr(exc, "status_code", None)
            return {"ok": False, "error": type(exc).__name__ + (f" HTTP {code}" if code else ""),
                    "latency_s": round(time.perf_counter() - t0, 2)}
        latency = round(time.perf_counter() - t0, 2)
        usage = {}
        u = getattr(resp, "usage", None)
        for k in ("input_tokens", "output_tokens", "total_tokens"):
            v = getattr(u, k, None)
            if isinstance(v, int):
                usage[k] = v
        rt = getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", None)
        if isinstance(rt, int):
            usage["reasoning_tokens"] = rt
        status = getattr(resp, "status", None)
        base = {"latency_s": latency, "usage": usage, "model_actual": getattr(resp, "model", None), "response_status": status}
        if status and status != "completed":
            return {"ok": False, "error": f"incomplete:{status}", **base}
        text = getattr(resp, "output_text", None) or ""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"ok": False, "error": "json_invalid", **base}
        return {"ok": True, "data": data, **base}


class MockBaseline:
    """결정적 가짜(테스트·리허설). 계획서 해시로 위험 3개를 만든다. 결과에 mock이라고 적힌다."""

    name = "mock"

    def __init__(self, model: str = "mock-baseline-v1", effort: str = EFFORT, script: list[dict[str, Any]] | None = None) -> None:
        self.model = model
        self.effort = effort
        self.script = list(script or [])
        self.calls = 0

    def generate(self, instructions: str, plan_text: str) -> dict[str, Any]:
        self.calls += 1
        if self.script:
            return self.script.pop(0)
        h = hashlib.sha256(plan_text.encode("utf-8")).hexdigest()[:6]
        risks = [
            {"title": f"평가 설계 위험 {h}", "description": "비교 기준과 평가 지표가 계획서에 정해져 있지 않다."},
            {"title": "재현성 정보 부족", "description": "데이터 분할과 하이퍼파라미터 선택 절차가 빠져 있다."},
            {"title": "일반화 범위 과장", "description": "한 도메인 결과로 넓은 적용성을 주장할 위험이 있다."},
        ]
        return {"ok": True, "data": {"risks": risks}, "latency_s": 0.0, "usage": {}, "model_actual": self.model}


def make_provider(name: str) -> Provider:
    if name == "openai":
        return OpenAIBaseline()
    if name == "mock":
        return MockBaseline()
    raise ValueError(f"알 수 없는 provider {name!r}")


def cache_key(provider: Provider, prompt_version: str, plan_id: str) -> str:
    raw = f"{provider.name}|{provider.model}|{provider.effort}|{prompt_version}|{plan_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_cached(plan: dict[str, Any], provider: Provider, cache_dir: Path, prompt: tuple[str, str] | None = None) -> dict[str, Any]:
    """계획서 하나 → 캐시 항목(있으면 읽고, 없으면 부르고 쓴다)."""
    instructions, version = prompt or load_prompt()
    key = cache_key(provider, version, plan["plan_id"])
    path = Path(cache_dir) / f"{key}.json"
    if path.is_file():
        entry = read_json(path)
        entry["cache_hit"] = True
        return entry
    attempts = []
    final: dict[str, Any] | None = None
    final_probs: list[str] = ["no attempt"]
    for _ in range(MAX_ATTEMPTS):
        g = provider.generate(instructions, plan["plan_text"])
        probs = output_problems(g.get("data")) if g.get("ok") else [str(g.get("error", "error"))]
        attempts.append({k: g.get(k) for k in ("ok", "error", "latency_s", "usage", "model_actual", "response_status")} | {"problems": probs})
        # 형식이 깨진 응답(위험 3개가 아님 등)은 쓰지 않는다. 설명 2문장 초과만 있는 응답은 자르고 쓸 수 있다.
        usable = g.get("ok") and not [p for p in probs if "문장 >" not in p]
        if usable and (final is None or not probs):
            final, final_probs = g, probs
        elif final is None:
            final_probs = probs
        if usable and not probs:
            break
    entry = {
        "key": key,
        "system": SYSTEM,
        "provider": provider.name,
        "model_requested": provider.model,
        "model_actual": (final or {}).get("model_actual"),
        "effort": provider.effort,
        "prompt_version": version,
        "plan_id": plan["plan_id"],
        "plan_work_id": plan["work_id"],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "attempts": attempts,
        "ok": final is not None,
        "output": (final or {}).get("data"),
        "final_problems": final_probs,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    entry["cache_hit"] = False
    return entry


def riskset_from_entry(entry: dict[str, Any], *, condition: str, work_id: str) -> dict[str, Any]:
    risks: list[dict[str, Any]] = []
    notes: list[str] = []
    out = entry.get("output") or {}
    if entry.get("ok") and isinstance(out.get("risks"), list):
        for rank, r in enumerate(out["risks"][:K], 1):
            risks.append(make_risk(rank, str(r.get("title", "")), str(r.get("description", "")), evidence_ok=False))
        if any(r["trimmed"] for r in risks):
            notes.append("설명 2문장 초과 → 앞 2문장으로 자름")
    if entry.get("final_problems"):
        notes.append("형식 문제: " + "; ".join(map(str, entry["final_problems"])))
    status = "ok" if entry.get("ok") and len(risks) == K else "error"
    generator = {"openai": "astra", "mock": "mock"}.get(entry.get("provider", ""), entry.get("provider", ""))
    return make_riskset(
        system=SYSTEM, condition=condition, work_id=work_id, plan_work_id=entry["plan_work_id"], plan_id=entry["plan_id"],
        risks=risks, status=status, generator=generator, model=entry.get("model_actual") or entry.get("model_requested"),
        notes=notes,
        meta={"prompt_version": entry.get("prompt_version"), "effort": entry.get("effort"),
              "model_requested": entry.get("model_requested"), "cache_key": entry.get("key")},
    )


def run(sample: dict[str, Any], plans: dict[str, dict[str, Any]], provider: Provider, cache_dir: Path, *,
        limit: int | None = None, conditions: tuple[str, ...] = ("real", "shuffle"), workers: int = 4) -> list[dict[str, Any]]:
    items = sample["items"][:limit] if limit else sample["items"]
    pairs = {p["work_id"]: p["plan_work_id"] for p in sample["shuffle_pairs"]}
    jobs: list[tuple[str, str, str]] = []  # (condition, 판정 논문 i, 계획서 논문 j)
    for it in items:
        wid = it["work_id"]
        if "real" in conditions:
            jobs.append(("real", wid, wid))
        if "shuffle" in conditions:
            jobs.append(("shuffle", wid, pairs[wid]))
    prompt = load_prompt()
    needed = sorted({j for _, _, j in jobs})
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        entries = dict(zip(needed, ex.map(lambda j: generate_cached(plans[j], provider, cache_dir, prompt), needed)))
    return [riskset_from_entry(entries[j], condition=c, work_id=i) for c, i, j in jobs]


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(description="일반 LLM 기준선: 계획서만 넣고 위험 3개")
    ap.add_argument("--provider", choices=("openai", "mock"), default=None, help="기본 NEUMANN_LLM_PROVIDER(없으면 openai)")
    ap.add_argument("--sample", type=Path, default=None)
    ap.add_argument("--plans", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=None, help="표본 앞 N편만")
    ap.add_argument("--conditions", default="real,shuffle")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=None, help="기본 data/eval/riskset_baseline_llm.jsonl(--limit면 .firstN)")
    args = ap.parse_args(argv)

    provider = make_provider(args.provider or os.environ.get("NEUMANN_LLM_PROVIDER") or "openai")
    sample = read_json(args.sample or eval_dir() / "backtest_sample.json")
    plans = {r["work_id"]: r for r in read_jsonl(args.plans or eval_dir() / "backtest_plans.jsonl")}
    conditions = tuple(c.strip() for c in args.conditions.split(",") if c.strip())
    cache_dir = eval_dir() / "baseline_llm_cache"
    t0 = time.perf_counter()
    rows = run(sample, plans, provider, cache_dir, limit=args.limit, conditions=conditions, workers=args.workers)
    name = "riskset_baseline_llm" + (f".first{args.limit}" if args.limit else "") + (".mock" if provider.name == "mock" else "")
    out = args.out or eval_dir() / f"{name}.jsonl"
    sha = write_jsonl(out, rows)
    _, version = load_prompt()
    ok = sum(1 for r in rows if r["status"] == "ok")
    print(f"provider {provider.name} · 요청 모델 {provider.model} · effort {provider.effort} · 프롬프트 {version}")
    print(f"위험 묶음 {len(rows)}건(조건 {conditions}) · 형식 통과 {ok} · {time.perf_counter() - t0:.1f}s")
    for r in rows:
        print(f"- [{r['condition']}] {r['work_id']} (계획서 {r['plan_work_id']}) status={r['status']} model={r['model']} 위험 {r['n_risks']}개")
        for x in r["risks"]:
            print(f"    {x['rank']}. ({x['sentences']}문장{', 자름' if x['trimmed'] else ''}) {x['text']}")
        for n in r["notes"]:
            print(f"    note: {n}")
    print(f"sha256 {sha} → {out}")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
