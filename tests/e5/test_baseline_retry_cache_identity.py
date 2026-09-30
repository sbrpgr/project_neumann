"""B3: 기준선(eval/baseline_llm.py) 독립 FAIL 2건 재현 — 합성 SDK만 쓴다(자격 증명·네트워크 없음).

FAIL ① 승인 철회로 재시도가 잠기면 앞 응답이 있어도 결과는 성공(ok/status=ok)이 아니다.
FAIL ② 캐시 키는 요청 모델이 아니라 실효 provider·model·effort(가드 뒤 sol)로 잡고,
       옛 캐시는 기록(provider·요청 모델·effort·프롬프트·계획서·키)이 실효 값과 맞을 때만 재사용한다.
"""

from __future__ import annotations

import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from eval import baseline_llm as bl
from neumann import config

PLAN = {"work_id": "synthetic", "plan_id": "b" * 64, "plan_text": "synthetic plan"}
PROMPT = ("instructions", "synthetic-v1")
SOL = bl.DEFAULT_MODEL
ASTRA = "gpt-6-astra"


def _risks(desc: str) -> str:
    return json.dumps({"risks": [{"title": f"Risk {i}", "description": desc} for i in range(3)]})


class FakeResponses:
    def __init__(self, desc: str = "One sentence.", on_call=None):
        self.calls: list[dict] = []
        self.desc = desc
        self.on_call = on_call

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.on_call:
            self.on_call()
        return SimpleNamespace(status="completed", model=kwargs["model"], usage=None, output_text=_risks(self.desc))


@pytest.fixture(autouse=True)
def synthetic_sdk_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Real SDK/settings access is forbidden in this test")

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=forbidden))
    monkeypatch.setattr(config, "get_settings", forbidden)
    monkeypatch.delenv("NEUMANN_ALLOW_ASTRA", raising=False)
    monkeypatch.delenv("NEUMANN_LLM_MODEL", raising=False)  # 셸에 남은 모델 설정과 무관하게 기본 모델에서 시작
    monkeypatch.setattr(config, "live_llm_allowed", lambda: True)  # 합성 SDK의 로컬 권한만 mock


def _expected_key(model: str, provider: str = "openai", effort: str = bl.EFFORT) -> str:
    raw = f"{provider}|{model}|{effort}|{PROMPT[1]}|{PLAN['plan_id']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _files(tmp_path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir())


# ── FAIL ① ────────────────────────────────────────────────────────────────


def test_retry_locked_after_usable_first_response_is_not_success(monkeypatch, tmp_path):
    """첫 응답은 설명 3문장(자르면 쓸 수 있음) → 재시도 전에 승인 철회 → 재시도 잠김."""
    sdk = FakeResponses("a. b. c.", on_call=lambda: monkeypatch.setattr(config, "live_llm_allowed", lambda: False))
    p = bl.OpenAIBaseline(client=SimpleNamespace(responses=sdk))
    entry = bl.generate_cached(PLAN, p, tmp_path, prompt=PROMPT)
    assert len(sdk.calls) == 1 and len(entry["attempts"]) == 2
    assert entry["locked"] is True
    assert entry["ok"] is False and entry["output"] is None  # 잠긴 결과를 성공으로 적지 않는다
    assert entry["attempts"][1].get("locked") is True
    assert any("locked" in str(x) for x in entry["final_problems"])
    assert _files(tmp_path) == []  # 잠긴 결과는 캐시에 쓰지 않는다
    row = bl.riskset_from_entry(entry, condition="real", work_id=PLAN["work_id"])
    assert row["status"] == "error" and row["n_risks"] == 0 and row["generator"] == "none"
    assert any("잠김" in n for n in row["notes"])


def test_locked_entry_never_reports_ok_even_if_flags_disagree():
    """이전 버전이 남긴 모순 기록(locked=True·ok=True)도 행에서 성공으로 읽지 않는다."""
    entry = {"ok": True, "locked": True, "provider": "openai", "model_requested": SOL, "model_actual": SOL,
             "output": json.loads(_risks("One.")), "final_problems": [], "plan_id": PLAN["plan_id"],
             "plan_work_id": PLAN["work_id"], "prompt_version": PROMPT[1], "effort": bl.EFFORT, "key": "k"}
    row = bl.riskset_from_entry(entry, condition="real", work_id=PLAN["work_id"])
    assert row["status"] == "error" and row["n_risks"] == 0 and row["generator"] == "none"


# ── FAIL ② ────────────────────────────────────────────────────────────────


def test_astra_withdrawn_before_run_caches_under_effective_sol_key(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUMANN_ALLOW_ASTRA", "1")
    sdk = FakeResponses()
    p = bl.OpenAIBaseline(model=ASTRA, client=SimpleNamespace(responses=sdk))
    monkeypatch.delenv("NEUMANN_ALLOW_ASTRA")
    first = bl.generate_cached(PLAN, p, tmp_path, prompt=PROMPT)
    assert [c["model"] for c in sdk.calls] == [SOL]
    assert first["model_requested"] == SOL and first["key"] == _expected_key(SOL)
    assert _files(tmp_path) == [f"{_expected_key(SOL)}.json"]
    second = bl.generate_cached(PLAN, p, tmp_path, prompt=PROMPT)
    assert second["cache_hit"] is True and second["key"] == first["key"]
    assert len(sdk.calls) == 1 and len(_files(tmp_path)) == 1


def test_astra_withdrawn_between_lookup_and_sdk_call(monkeypatch, tmp_path):
    """조회 때는 Astra가 허용(키도 Astra)이었다가 SDK 호출 직전에 철회 → 실제 요청은 Sol. Astra 키에 Sol 결과를 쓰지 않는다."""
    monkeypatch.setenv("NEUMANN_ALLOW_ASTRA", "1")
    sdk = FakeResponses()
    p = bl.OpenAIBaseline(model=ASTRA, client=SimpleNamespace(responses=sdk))
    original = bl.OpenAIBaseline._get_client

    def acquire_and_withdraw_astra(self):
        monkeypatch.delenv("NEUMANN_ALLOW_ASTRA", raising=False)
        return original(self)

    monkeypatch.setattr(bl.OpenAIBaseline, "_get_client", acquire_and_withdraw_astra)
    entry = bl.generate_cached(PLAN, p, tmp_path, prompt=PROMPT)
    assert [c["model"] for c in sdk.calls] == [SOL]
    assert entry["ok"] is True and entry["model_requested"] == SOL and entry["model_actual"] == SOL
    assert entry["key"] == _expected_key(SOL)
    assert f"{_expected_key(ASTRA)}.json" not in _files(tmp_path)
    assert all(a.get("model_requested") == SOL for a in entry["attempts"])
    again = bl.generate_cached(PLAN, p, tmp_path, prompt=PROMPT)
    assert again["cache_hit"] is True and len(sdk.calls) == 1


def test_cache_key_uses_effective_provider_model_effort(monkeypatch):
    fake = SimpleNamespace(responses=FakeResponses())
    astra_without_permission = bl.OpenAIBaseline(client=fake)
    astra_without_permission.model = ASTRA  # 생성 뒤 요청 모델이 바뀌어도 키는 실효 모델
    assert bl.cache_key(astra_without_permission, PROMPT[1], PLAN["plan_id"]) == _expected_key(SOL)
    monkeypatch.setenv("NEUMANN_ALLOW_ASTRA", "1")
    assert bl.cache_key(astra_without_permission, PROMPT[1], PLAN["plan_id"]) == _expected_key(ASTRA)
    high = bl.OpenAIBaseline(client=fake, effort="high")
    assert bl.cache_key(high, PROMPT[1], PLAN["plan_id"]) == _expected_key(SOL, effort="high")
    mock = bl.MockBaseline()
    assert bl.cache_key(mock, PROMPT[1], PLAN["plan_id"]) == _expected_key("mock-baseline-v1", provider="mock")


def _legacy_entry(key: str, *, model_requested: str, model_actual: str, provider: str = "openai") -> dict:
    """옛 형식 캐시 항목(시도별 model_requested 없음)."""
    return {"key": key, "system": bl.SYSTEM, "provider": provider, "model_requested": model_requested,
            "model_actual": model_actual, "effort": bl.EFFORT, "prompt_version": PROMPT[1], "plan_id": PLAN["plan_id"],
            "plan_work_id": PLAN["work_id"], "created_at": "2026-09-30T00:00:00+00:00",
            "attempts": [{"ok": True, "problems": []}], "ok": True, "output": json.loads(_risks("Cached.")),
            "final_problems": []}


@pytest.mark.parametrize("recorded", [
    {"model_requested": ASTRA, "model_actual": SOL},      # 58b56fb 전·후 섞인 기록
    {"model_requested": SOL, "model_actual": ASTRA},      # 실제 모델이 Astra
    {"model_requested": SOL, "model_actual": SOL, "provider": "mock"},
])
def test_old_cache_with_mismatched_record_is_not_reused(tmp_path, recorded):
    key = _expected_key(SOL)
    (tmp_path / f"{key}.json").write_text(json.dumps(_legacy_entry(key, **recorded)), encoding="utf-8")
    sdk = FakeResponses("Fresh.")
    p = bl.OpenAIBaseline(client=SimpleNamespace(responses=sdk))
    entry = bl.generate_cached(PLAN, p, tmp_path, prompt=PROMPT)
    assert entry["cache_hit"] is False and len(sdk.calls) == 1
    assert entry["stale_cache"]  # 무시한 사유를 남긴다
    stored = json.loads((tmp_path / f"{key}.json").read_text(encoding="utf-8"))
    assert stored["model_requested"] == SOL and stored["provider"] == "openai"
    assert stored["output"]["risks"][0]["description"] == "Fresh."


def test_unreadable_cache_file_is_replaced_not_crash(tmp_path):
    key = _expected_key(SOL)
    (tmp_path / f"{key}.json").write_text("{not json", encoding="utf-8")
    sdk = FakeResponses()
    entry = bl.generate_cached(PLAN, bl.OpenAIBaseline(client=SimpleNamespace(responses=sdk)), tmp_path, prompt=PROMPT)
    assert entry["ok"] is True and entry["cache_hit"] is False and len(sdk.calls) == 1


def test_matching_legacy_cache_is_reused_without_calls(monkeypatch, tmp_path):
    """기록이 실효 값과 맞는 옛 캐시(이미 돈을 쓴 sol 결과)는 다시 부르지 않는다. Astra는 허용될 때만 Astra 키를 읽는다."""
    for model in (SOL, ASTRA):
        key = _expected_key(model)
        (tmp_path / f"{key}.json").write_text(
            json.dumps(_legacy_entry(key, model_requested=model, model_actual=model)), encoding="utf-8")
    sdk = FakeResponses()
    p = bl.OpenAIBaseline(model=ASTRA, client=SimpleNamespace(responses=sdk))  # 권한 없음 → Sol
    entry = bl.generate_cached(PLAN, p, tmp_path, prompt=PROMPT)
    assert entry["cache_hit"] is True and entry["model_requested"] == SOL and sdk.calls == []
    monkeypatch.setenv("NEUMANN_ALLOW_ASTRA", "1")
    p_astra = bl.OpenAIBaseline(model=ASTRA, client=SimpleNamespace(responses=sdk))
    entry = bl.generate_cached(PLAN, p_astra, tmp_path, prompt=PROMPT)
    assert entry["cache_hit"] is True and entry["model_requested"] == ASTRA and sdk.calls == []
