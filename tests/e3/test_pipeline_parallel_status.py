"""E3-L1z(PM 추가 범위): 병렬 v1 단계의 status 합치기 — astra 이름 provider + 단계 실패에서 순차와 같다.

E3-L1y 검증(§8 M2)에서 `_merge_v1`의 status 합치기를 지워도 `test_pipeline_parallel.py`가 통과했다. 그 파일의
병렬=순차 시나리오는 mock 이름 provider라 결과 status가 처음부터 degraded였고(`is_mock`), astra 이름 시나리오에는
실패가 없어 status가 ok로 남아도 맞았기 때문이다. 여기서는 기본 status가 ok인 astra 이름 provider(`openai`)로
v1 단계를 실패(시간 초과·API 오류·깨진 응답·모듈 예외)시켜, 결과 status·단계별 state·생성 주체 표기가 순차 실행과
같고 강등이 ok로 숨지 않는지 본다. mock·fixture만(실제 API 없음).
"""

from __future__ import annotations

from typing import Any

import pytest

import neumann.pipeline as pl
from neumann.analyze import checklist as checklist_mod
from neumann.analyze import review as review_mod
from neumann.analyze import validate as validate_mod
from neumann.analyze.mock_responders import default_responders
from neumann.llm import MockProvider
from neumann.pipeline import V1_STAGES, run_premortem
from tests.e3.corpus import PLAN_BATTERY, build_backend

V1 = [name for name, _ in V1_STAGES]
VOLATILE = {"elapsed_s", "latency_s", "total_s", "timings_s", "v1_wall_s", "v1_parallel", "generated_at"}
MODEL = "gpt-6.1-sol"


class AstraLike(MockProvider):
    """응답은 결정적이지만 이름이 openai(생성 주체 astra)라 결과의 기본 status가 ok인 시험용 provider."""

    name = "openai"


def _norm(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in x.items() if k not in VOLATILE}
    if isinstance(x, list):
        return [_norm(v) for v in x]
    return x


def _labels(r) -> dict[str, Any]:
    """단계별 state와 결과 섹션의 생성 주체·모델 표기."""
    sem = (r.verification or {}).get("semantic") or {}
    return {
        "status": r.status,
        "stages": {s.stage: s.state for s in r.stages},
        "expected_review": ((r.expected_review or {}).get("generator"), (r.expected_review or {}).get("model")),
        "checklist": sorted({(i.get("generator"), i.get("model")) for i in (r.checklist or [])}, key=str),
        "semantic": (sem.get("generator"), sem.get("model"), sem.get("status")),
    }


def _run_both(monkeypatch, make_llm) -> tuple[Any, Any]:
    monkeypatch.setattr(pl, "_load_fitness", lambda: None)  # 적합성 단계는 이 검사와 무관(ok로 둔다)
    out = {}
    for mode in (False, True):
        monkeypatch.setattr(pl, "V1_PARALLEL", mode)
        out[mode] = run_premortem(PLAN_BATTERY, llm=make_llm(), backend=build_backend(), cache_dir=None,
                                  session_id="sess-e3-l1z")
    return out[False], out[True]


def _astra(fail: dict[str, str] | None = None, broken: tuple[str, ...] = ()) -> AstraLike:
    """fail: 과제 → 실패 분류(timeout·api_error). broken: 깨진 JSON 문자열을 돌려줄 과제."""
    responders = {**default_responders(), **{t: (lambda call: "{깨진 JSON") for t in broken}}
    return AstraLike(responders, model=MODEL, fail=fail)


# provider 실패(모듈이 규칙·미검증으로 물러나 degraded): 단계 하나씩, 둘, 셋 다, 깨진 응답
FAILS: dict[str, tuple[dict[str, str], tuple[str, ...]]] = {
    **{f"timeout_{t}": ({t: "timeout"}, ()) for t in V1},
    "api_error_review_and_validate": ({"expected_review": "api_error", "semantic_validate": "api_error"}, ()),
    "broken_json_checklist": ({}, ("checklist",)),
    "api_error_all_v1": ({t: "api_error" for t in V1}, ()),
}


def test_astra_like_without_failure_is_ok_in_both_modes(monkeypatch) -> None:
    """대조군: 실패가 없으면 순차·병렬 모두 ok(아래 검사들이 status를 처음부터 degraded로 보지 않는다는 근거)."""
    seq, par = _run_both(monkeypatch, _astra)
    assert seq.status == par.status == "ok"
    assert all(s.state in ("ok", "skipped") for s in par.stages)
    assert _labels(par) == _labels(seq)
    assert par.expected_review["generator"] == "astra"


@pytest.mark.parametrize("scenario", sorted(FAILS))
def test_astra_like_stage_failure_status_equals_sequential(monkeypatch, scenario: str) -> None:
    fail, broken = FAILS[scenario]
    failed = [t for t in V1 if t in fail or t in broken]
    seq, par = _run_both(monkeypatch, lambda: _astra(fail, broken))
    # 순차 기준값이 맞는지 먼저: 실패한 단계만 degraded, 결과 status는 degraded(ok로 숨기지 않는다)
    assert {t: _labels(seq)["stages"][t] for t in V1} == {t: "degraded" if t in failed else "ok" for t in V1}
    assert seq.status == "degraded"
    # 병렬 = 순차: status, 단계별 state, 생성 주체·모델 표기, 그리고 결과 전체
    assert par.status == seq.status
    assert _labels(par) == _labels(seq)
    assert _norm(par.model_dump(mode="json")) == _norm(seq.model_dump(mode="json"))
    if "expected_review" not in failed:  # 실패하지 않은 단계의 astra 표기는 그대로
        assert par.expected_review["generator"] == "astra"


@pytest.mark.parametrize(
    ("module", "func", "stage"),
    [
        (review_mod, "attach_expected_review", "expected_review"),
        (checklist_mod, "attach_checklist", "checklist"),
        (validate_mod, "attach_validation", "semantic_validate"),
    ],
)
def test_astra_like_stage_exception_status_equals_sequential(monkeypatch, module, func: str, stage: str) -> None:
    """모듈 예외(단계 error)도 병렬 합치기에서 status가 degraded로 올라간다(순차와 같다)."""

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("시험용 예외")

    monkeypatch.setattr(module, func, boom)
    seq, par = _run_both(monkeypatch, _astra)
    assert _labels(seq)["stages"][stage] == "error"
    assert seq.status == "degraded"
    assert par.status == seq.status
    assert _labels(par) == _labels(seq)
    assert _norm(par.model_dump(mode="json")) == _norm(seq.model_dump(mode="json"))
