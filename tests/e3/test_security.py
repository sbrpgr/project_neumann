"""SEC-1 S-04·S-05 회귀 테스트.

S-04: 예외 원문·API 오류 문구·경로·키 모양 문자열이 결과 JSON(stages.detail, notices, 사유)에 나가지 않는다.
      서버 로그에는 예외 종류·위치만 남고 메시지(키·경로)는 남지 않는다.
S-05: mock provider 결과는 status를 ok로 두지 않고 degraded + "mock provider(테스트용)" 안내를 붙인다.
"""

from __future__ import annotations

import logging

import httpx
import openai
import pytest

import neumann.analyze.backend as backend_mod
from neumann.analyze.backend import FixtureBackend
from neumann.analyze.mock_responders import default_responders
from neumann.llm import LLMCall, MockProvider, OpenAIProvider, validate_output
from neumann.pipeline import MOCK_NOTICE, run_premortem, safe_text
from tests.e3.corpus import PLAN_BATTERY, build, build_backend

# 가짜 값(실제 키 아님). 저장소 스캐너에 걸리지 않게 실행 중에 조립한다.
FAKE_KEY = "s" + "k-proj-" + "Zq7" * 12
FAKE_PATH = "C:\\Users\\alice\\secret_project\\data\\index\\manifest.json"
FAKE_POSIX = "/home/alice/secret_project/index"
LEAKS = (FAKE_KEY, "alice", "secret_project", "C:\\Users", "C:\\\\Users", FAKE_POSIX)


def _dump(result) -> str:
    return result.model_dump_json()


def _assert_clean(text: str) -> None:
    for leak in LEAKS:
        assert leak not in text, f"응답에 새어 나감: {leak!r}"


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/responses")


# ── S-04 ─────────────────────────────────────────────────────────────────


def test_safe_text_strips_paths_and_keys():
    s = safe_text(f"open {FAKE_PATH} failed; {FAKE_POSIX} ; key={FAKE_KEY}; Bearer abc.def")
    assert "[path]" in s and "[redacted]" in s
    _assert_clean(s)
    assert safe_text("상위 점수 0.540, L12") == "상위 점수 0.540, L12"


def test_stage_exception_message_not_in_result_but_type_is(caplog):
    class Broken(FixtureBackend):
        def search(self, *a, **kw):
            raise RuntimeError(f"cannot open {FAKE_PATH} with {FAKE_KEY}")

    works, reviews = build()
    with caplog.at_level(logging.DEBUG):
        r = run_premortem(PLAN_BATTERY, provider="mock", backend=Broken(works, reviews), cache_dir=None)
    out = _dump(r)
    _assert_clean(out)
    st = next(s for s in r.stages if s.stage == "search")
    assert st.state == "error" and "내부 오류(RuntimeError)" in st.detail
    # 서버 로그: 예외 종류와 위치는 남고, 메시지(경로·키)는 없다
    logs = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "RuntimeError" in logs and "test_security.py" in logs
    _assert_clean(logs)


def test_backend_open_failure_path_not_in_result(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError(f"색인이 없다: {FAKE_PATH}")

    monkeypatch.setattr(backend_mod, "make_backend", boom)
    r = run_premortem(PLAN_BATTERY, provider="mock", cache_dir=None)
    _assert_clean(_dump(r))
    st = next(s for s in r.stages if s.stage == "search")
    assert st.state == "skipped" and "FileNotFoundError" in st.detail


def test_extraction_batch_exception_message_not_in_result():
    responders = default_responders()

    def exploding(call: LLMCall):
        raise RuntimeError(f"{FAKE_PATH} {FAKE_KEY}")

    responders["extract_issues"] = exploding
    r = run_premortem(PLAN_BATTERY, llm=MockProvider(responders), backend=build_backend(), cache_dir=None)
    _assert_clean(_dump(r))
    st = next(s for s in r.stages if s.stage == "extract_issues")
    assert st.state == "degraded" and "RuntimeError" in st.detail


class _AuthFailClient:
    """401 오류를 던지는 가짜 OpenAI 클라이언트. 오류 문구에 키 조각·경로를 넣는다(실제 OpenAI 401 문구 모사)."""

    def __init__(self) -> None:
        self.responses = self

    def with_options(self, timeout):
        return self

    def create(self, **kwargs):
        body = {"error": {"message": f"Incorrect API key provided: {FAKE_KEY}. See {FAKE_PATH}",
                          "code": "invalid_api_key", "type": "invalid_request_error"}}
        raise openai.AuthenticationError(
            f"Error code: 401 - {body}", response=httpx.Response(401, request=_req()), body=body
        )


def test_api_error_message_not_in_reason_result_or_logs(caplog):
    p = OpenAIProvider(api_key=None, model="gpt-6-astra", client=_AuthFailClient())
    with caplog.at_level(logging.DEBUG):
        res = p.complete_json(LLMCall(task="t", instructions="x", payload={}, schema={"type": "object"}, schema_name="s"))
        r = run_premortem(PLAN_BATTERY, llm=p, backend=build_backend(), cache_dir=None)
    assert not res.ok and res.error == "api_error"
    assert "HTTP 401" in res.detail and "invalid_api_key" in res.detail
    _assert_clean(res.reason())
    assert "Incorrect API key" not in res.reason()
    out = _dump(r)
    _assert_clean(out)
    assert "Incorrect API key" not in out
    assert r.status == "degraded" and r.risk_cards and all(c.generator.value == "rule" for c in r.risk_cards)
    qa = next(s for s in r.stages if s.stage == "query_axes")
    assert "호출 실패(API 오류" in qa.detail and "비상 규칙 경로" in qa.detail
    logs = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "api_error" in logs
    _assert_clean(logs)
    assert "Incorrect API key" not in logs


def test_schema_error_detail_does_not_echo_model_output():
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"tag": {"type": "string", "enum": ["a"]}}, "required": ["tag"]}
    _, err, detail = validate_output('{"tag": "' + FAKE_PATH.replace("\\", "/") + " " + FAKE_KEY + '"}', schema)
    assert err == "schema_invalid" and "tag" in detail and "enum" in detail
    _assert_clean(detail)
    assert "alice" not in detail


# ── S-05 ─────────────────────────────────────────────────────────────────


def test_mock_provider_result_is_degraded_with_notice():
    r = run_premortem(PLAN_BATTERY, provider="mock", backend=build_backend(), cache_dir=None)
    assert r.risk_cards and all(c.generator.value == "mock" for c in r.risk_cards)
    assert all(s.state == "ok" for s in r.stages)  # 단계는 정상이어도
    assert r.status == "degraded" and MOCK_NOTICE in r.notices


def test_mock_zero_card_result_is_also_degraded():
    from tests.e3.corpus import RECIPE

    r = run_premortem(RECIPE, provider="mock", backend=build_backend(), cache_dir=None)
    assert r.risk_cards == [] and r.status == "degraded" and MOCK_NOTICE in r.notices


def test_real_provider_result_stays_ok():
    """대조: provider가 openai(astra)로 표기되는 경로는 단계가 모두 ok면 status ok, mock 안내 없음."""

    class AstraLike(MockProvider):  # 응답은 결정적이지만 provider 이름은 openai(생성 주체 astra)
        name = "openai"

    llm = AstraLike(default_responders(), model="gpt-6-astra")
    r = run_premortem(PLAN_BATTERY, llm=llm, backend=build_backend(), cache_dir=None)
    assert r.risk_cards and all(c.generator.value == "astra" for c in r.risk_cards)
    assert r.status == "ok" and MOCK_NOTICE not in r.notices


@pytest.mark.parametrize("provider", ["off"])
def test_off_provider_is_degraded_without_mock_notice(provider):
    r = run_premortem(PLAN_BATTERY, provider=provider, backend=build_backend(), cache_dir=None)
    assert r.status == "degraded" and MOCK_NOTICE not in r.notices
