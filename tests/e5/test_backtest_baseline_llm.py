"""일반 LLM 기준선: 프롬프트 공개, 형식(정확히 3개·2문장), 재시도·자르기, 캐시, 셔플 재사용, 요청 모양."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from eval import baseline_llm as bl
from neumann import config

PLAN = {"work_id": "ns:P1", "plan_id": "a" * 64, "plan_text": "We propose a graph model for protein stability."}


def _risks(desc: str = "하나다.") -> dict:
    return {"risks": [{"title": f"위험 {i}", "description": desc} for i in range(1, 4)]}


def test_prompt_file_is_public_and_has_core_sentence():
    text, version = bl.load_prompt()
    assert "이 연구계획서가 심사에서 받을 위험 3개를 구체적으로" in text
    assert "정확히 3개" in text and "2문장" in text
    assert len(version) == 16
    # 코퍼스·검색·택소노미를 주지 않는다: 프롬프트에 위험 코드 목록이 없다
    assert "R1" not in text and "택소노미" not in text


def test_output_problems():
    assert bl.output_problems(_risks()) == []
    assert any("정확히 3" in p for p in bl.output_problems({"risks": _risks()["risks"][:2]}))
    assert any("문장 >" in p for p in bl.output_problems(_risks("하나. 둘. 셋.")))
    assert bl.output_problems({"x": 1}) == ["risks 배열 없음"]


def test_generate_cached_mock_and_cache_hit(tmp_path):
    p = bl.MockBaseline()
    e1 = bl.generate_cached(PLAN, p, tmp_path)
    assert e1["ok"] and e1["cache_hit"] is False and p.calls == 1
    assert e1["model_actual"] == "mock-baseline-v1" and e1["final_problems"] == []
    e2 = bl.generate_cached(PLAN, p, tmp_path)
    assert e2["cache_hit"] is True and p.calls == 1  # 다시 부르지 않는다
    rs = bl.riskset_from_entry(e2, condition="real", work_id="ns:P1")
    assert rs["status"] == "ok" and rs["n_risks"] == 3 and rs["generator"] == "mock"
    assert all(not r["evidence_ok"] for r in rs["risks"])  # 일반 LLM은 원문 근거가 없다


def test_retry_then_trim(tmp_path):
    bad = {"ok": True, "data": _risks("하나. 둘. 셋."), "model_actual": "m"}
    good = {"ok": True, "data": _risks("하나다. 둘이다."), "model_actual": "m"}
    p = bl.MockBaseline(script=[bad, good])
    e = bl.generate_cached(PLAN, p, tmp_path)
    assert p.calls == 2 and e["final_problems"] == [] and len(e["attempts"]) == 2
    p2 = bl.MockBaseline(model="m2", script=[bad, bad])
    e2 = bl.generate_cached(PLAN, p2, tmp_path)
    rs = bl.riskset_from_entry(e2, condition="real", work_id="ns:P1")
    assert rs["status"] == "ok" and all(r["trimmed"] and r["sentences"] == 2 for r in rs["risks"])
    assert any("자름" in n for n in rs["notes"])
    p3 = bl.MockBaseline(model="m3", script=[{"ok": True, "data": {"risks": _risks()["risks"][:2]}}, {"ok": False, "error": "timeout"}])
    rs3 = bl.riskset_from_entry(bl.generate_cached(PLAN, p3, tmp_path), condition="real", work_id="ns:P1")
    assert rs3["status"] == "error" and rs3["n_risks"] == 0  # 개수가 틀린 응답은 쓰지 않는다


def test_run_shuffle_reuses_partner_plan(tmp_path):
    plans = {w: {"work_id": w, "plan_id": w[-1] * 64, "plan_text": f"plan {w}"} for w in ("ns:A", "ns:B", "ns:C")}
    sample = {"items": [{"work_id": w} for w in plans],
              "shuffle_pairs": [{"work_id": "ns:A", "plan_work_id": "ns:B"}, {"work_id": "ns:B", "plan_work_id": "ns:C"},
                                {"work_id": "ns:C", "plan_work_id": "ns:A"}]}
    p = bl.MockBaseline()
    rows = bl.run(sample, plans, p, tmp_path, workers=1)
    assert p.calls == 3  # 계획서 3개만 부른다(셔플은 캐시 재사용)
    shuf = {r["work_id"]: r for r in rows if r["condition"] == "shuffle"}
    real = {r["work_id"]: r for r in rows if r["condition"] == "real"}
    assert shuf["ns:A"]["plan_work_id"] == "ns:B"
    assert [x["text"] for x in shuf["ns:A"]["risks"]] == [x["text"] for x in real["ns:B"]["risks"]]
    assert len(bl.run(sample, plans, p, tmp_path, limit=1, conditions=("real",))) == 1


class _FakeResponses:
    def __init__(self):
        self.kwargs = None

    def create(self, **kw):
        self.kwargs = kw
        usage = SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30, output_tokens_details=SimpleNamespace(reasoning_tokens=5))
        return SimpleNamespace(status="completed", model="gpt-6-astra-2026-09-01", usage=usage,
                               output_text=json.dumps(_risks("설명이다."), ensure_ascii=False))


def test_openai_request_shape_plan_only(monkeypatch):
    # 합성 SDK만 쓴다. 권한은 로컬 함수로 mock하고 프로세스 live 플래그는 켜지 않는다.
    monkeypatch.setattr(config, "live_llm_allowed", lambda: True)
    monkeypatch.setattr(config, "astra_allowed", lambda: True)
    fake = _FakeResponses()
    prov = bl.OpenAIBaseline(model="gpt-6-astra", client=SimpleNamespace(responses=fake))
    instructions, _ = bl.load_prompt()
    g = prov.generate(instructions, PLAN["plan_text"])
    assert g["ok"] and g["model_actual"] == "gpt-6-astra-2026-09-01" and g["usage"]["reasoning_tokens"] == 5
    kw = fake.kwargs
    assert kw["model"] == "gpt-6-astra" and kw["input"] == PLAN["plan_text"] and kw["instructions"] == instructions
    assert kw["reasoning"] == {"effort": "medium"} and "temperature" not in kw and kw["store"] is False
    fmt = kw["text"]["format"]
    assert fmt["strict"] is True and fmt["schema"]["properties"]["risks"]["minItems"] == 3


@pytest.mark.skipif(os.getenv("NEUMANN_LIVE_TESTS") != "1", reason="실제 API는 NEUMANN_LIVE_TESTS=1일 때만")
def test_live_astra_one_plan(tmp_path):
    e = bl.generate_cached(PLAN, bl.OpenAIBaseline(), tmp_path)
    rs = bl.riskset_from_entry(e, condition="real", work_id="ns:P1")
    assert rs["status"] == "ok" and rs["n_risks"] == 3
