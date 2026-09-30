"""분야는 4cbf0f0과 비교, 승인된 300/600자 정책은 47acaba와 비교한다.

정책 기준의 분야 탐지만 고정 통합 소스 da5aba7에서 가져온다. 분야는 input_quality의
no_topic 분기와 metrics에도 쓰이므로, 필드를 삭제하는 대신 승인된 탐지기를 동일 입력에
실행한다. 정책/사전/판정/반환값 코드는 독립된 47acaba 원본이다. 시간값 elapsed_s만 제외하고
field, input_quality 전체, 사유, notice, status 등을 전부 비교한다. 기준이 없으면 실패한다.
"""

from __future__ import annotations

import functools
import json
import random
import subprocess
import types
from pathlib import Path
from typing import Any

import pytest

from neumann.analyze import fitness as current
from neumann.models import PlanDocument
from tests.fixtures.loader import DEMO_PLANS, NEGATIVE_PLAN, PLANS_DIR

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "src" / "neumann" / "api" / "templates"
BASE_REV = "4cbf0f0"  # E3-L1z 착수 때 main(판정 규칙은 E3-L1x 병합본 3968cad와 같다)
POLICY_REV = "47acaba"  # 승인된 L1s 300/600자 정책
FIELD_REV = "da5aba7"  # 이번 과제의 고정 통합 소스; 현재 런타임에서 기준을 가져오지 않는다
N_RANDOM = 240
SEED = 20260930


@functools.lru_cache(maxsize=3)
def revision_module(revision: str) -> types.ModuleType:
    """본선에서 생성된 지정 커밋 원본을 읽는다. 누락/읽기 실패는 skip하지 않는다."""
    try:
        proc = subprocess.run(
            ["git", "show", f"{revision}:src/neumann/analyze/fitness.py"],
            cwd=ROOT, capture_output=True, check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.fail(f"필수 차등 기준 {revision} 읽기 실패: {type(exc).__name__}")
    mod = types.ModuleType(f"neumann_fitness_{revision}")
    exec(compile(proc.stdout.decode("utf-8"), f"{revision}:fitness.py", "exec"), mod.__dict__)  # noqa: S102
    return mod


def _need_base() -> types.ModuleType:
    return revision_module(BASE_REV)


@functools.lru_cache(maxsize=1)
def policy_module() -> types.ModuleType:
    mod = revision_module(POLICY_REV)
    mod._FIELDS = revision_module(FIELD_REV)._FIELDS
    return mod


# ── 입력 모음 ─────────────────────────────────────────────────────────────


def document_inputs() -> list[tuple[str, str]]:
    """템플릿 5·예시(카탈로그) 3·데모 계획서 3·음성 대조 1. (이름, 본문)."""
    catalog = json.loads((TEMPLATES / "catalog.json").read_text(encoding="utf-8"))
    paths = [TEMPLATES / t["file"] for t in catalog["templates"]]
    paths += [ROOT / e["path"] for e in catalog["examples"]]
    paths += [PLANS_DIR / name for name in (*DEMO_PLANS, NEGATIVE_PLAN)]
    seen: dict[str, str] = {}
    for p in paths:
        seen.setdefault(p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8"))
    return list(seen.items())


# 무작위 입력 재료: 요소 사전·무관 사전·분야 표지와, 이번에 고친 경계 사례(조사·인지·neuro)를 섞는다.
_KO_WORDS = (
    "연구 목표는", "가설을", "규명하고자 한다", "방법으로", "모델을 학습한다", "실험 설계", "분석한다", "데이터를",
    "수집한다", "표본", "참가자 40명", "코호트", "정확도로", "평가한다", "기준선과 비교한다", "교차검증", "통계적으로",
    "재료", "큰술", "끓여", "여행", "숙소", "할인", "후렴", "일기", "전해액", "배터리", "단백질", "유전자", "기후",
    "기상", "유체", "의료", "환자", "진단", "자연어", "텍스트", "이미지", "뇌", "뇌우", "뉴런", "신경세포", "신경망",
    "신경 연산자", "신경 활동", "그리고", "또한", "우리는", "먼저", "결과", "이번", "과제별로", "단위로", "것인지",
)
_EN_WORDS = (
    "We propose", "our model", "the dataset", "baseline", "accuracy", "cross-validation", "participants", "GNN",
    "CNN", "recipe", "tablespoons", "hotel", "lyrics", "electrolyte", "battery", "protein", "DNA", "RNA", "climate",
    "weather", "plasma", "quantum", "NLP", "LLM", "images", "x-ray", "fMRI", "EEG", "brain", "brains", "cognitive",
    "neuroscience", "neurons", "neuroimaging", "neuromorphic", "neuro-symbolic", "Neuro symbolic", "neurosymbolic",
    "patients", "clinical", "cells", "genome", "fluids", "materials", "vision", "segmentation",
)
_PARTICLES = ("", "", "", "와", "과", "로", "으로", "을", "를", "은", "는", "의", "에서", "_data", "2", "-based", "s")
_COGNITION = (
    "효과적인지 과제별로", "나은 것인지 기능 단위로", "경도인지장애", "경도 인지장애", "인지 과제", "인지과제",
    "인지 기능 저하", "인지하고", "사회인지기능", "것인지 능력을", "공정한 것인지", "인지심리", "(인지 부하)",
)
_PUNCT = (",", ".", "(", ")", "—", ":", "·")


def _random_line(rng: random.Random) -> str:
    parts: list[str] = []
    for _ in range(rng.randint(1, 10)):
        kind = rng.random()
        if kind < 0.35:
            tok = rng.choice(_KO_WORDS)
        elif kind < 0.75:
            tok = rng.choice(_EN_WORDS) + rng.choice(_PARTICLES)
        elif kind < 0.9:
            tok = rng.choice(_COGNITION)
        else:
            tok = rng.choice(_PUNCT)
        sep = "" if parts and rng.random() < 0.15 else " "  # 가끔 붙여 써서 한글·로마자가 맞닿게 한다
        parts.append(sep + tok if parts else tok)
    return "".join(parts)


def random_inputs(n: int = N_RANDOM, seed: int = SEED) -> list[tuple[str, str]]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        lines = [_random_line(rng) for _ in range(rng.randint(1, 8))]
        if rng.random() < 0.2:
            lines.insert(rng.randrange(len(lines) + 1), "")  # 빈 줄
        out.append((f"random-{i:03d}", "\n".join(lines)))
    return out


# ── 비교 ──────────────────────────────────────────────────────────────────


class FixedLLM:
    """판정만 고정한 가짜 llm_call. 첫 줄을 요소 두 개의 근거로 쓰고 분야는 비워 규칙 분야로 떨어뜨린다."""

    generator = "mock"
    model = "fixed-e3-l1z"

    def __init__(self, verdict: str) -> None:
        self.verdict = verdict

    def __call__(self, schema: Any, instructions: str, llm_input: str, *, effort: str) -> dict[str, Any]:
        rows = json.loads(llm_input)["plan"].splitlines()
        first = [int(rows[0].split(":", 1)[0])] if rows else []
        elements = {
            e: {"present": i % 2 == 0, "plan_lines": first if i % 2 == 0 else []}
            for i, e in enumerate(current.ELEMENTS)
        }
        return {"verdict": self.verdict, "elements": elements, "field": "", "reason": "고정 응답(차등 검사)"}


def _deterministic_output(result: dict[str, Any]) -> dict[str, Any]:
    # 실행 시간만 비결정적이다. 정책·판정·분야를 포함한 결과 필드는 삭제하지 않는다.
    return {k: v for k, v in result.items() if k != "elapsed_s"}


def outcomes(mod: types.ModuleType, text: str) -> dict[str, Any]:
    """한 입력의 규칙·강등·고정 모델 판정 3종 전체(실행 시간 제외)."""
    plan = PlanDocument.from_text(text, "sess-e3-l1z")
    rule = mod.rule_fitness(plan)
    runs = {"rule": rule, "fallback": _deterministic_output(mod.assess_fitness(plan, None))}
    for v in ("research_plan", "not_research_plan", "uncertain"):
        runs[f"llm_{v}"] = _deterministic_output(mod.assess_fitness(plan, FixedLLM(v)))
    return {"field": rule["field"], "non_field": json.dumps(runs, ensure_ascii=False, sort_keys=True)}


def corpus() -> list[tuple[str, str]]:
    return document_inputs() + random_inputs()


def test_corpus_is_large_and_covers_all_verdicts() -> None:
    docs = corpus()
    assert len(random_inputs()) >= 200 and len(docs) >= 250
    verdicts = {current.rule_fitness(PlanDocument.from_text(t, "s"))["verdict"] for _, t in docs}
    prechecks = {current.rule_fitness(PlanDocument.from_text(t, "s"))["precheck"] for _, t in docs}
    assert verdicts == {"fit", "unfit", "uncertain"}
    assert "too_short" in prechecks


def test_non_field_outputs_equal_base() -> None:
    """승인된 정책+고정 분야 탐지 기준과 모든 결정적 반환값이 같다(251건 × 5)."""
    base = policy_module()
    diffs = []
    for name, text in corpus():
        before, after = outcomes(base, text), outcomes(current, text)
        if before["non_field"] != after["non_field"]:
            diffs.append(name)
    assert diffs == [], f"분야 밖 반환값이 달라진 입력 {len(diffs)}건: {diffs[:10]}"


def _field(mod: types.ModuleType, text: str) -> str | None:
    return mod.rule_fitness(PlanDocument.from_text(text, "sess-e3-l1z"))["field"]


def test_field_changes_are_exercised() -> None:
    """무작위 입력이 이번 수정(분야 표지)을 실제로 건드린다: 분야가 바뀐 입력이 있다."""
    base = _need_base()
    changed = [name for name, text in random_inputs() if _field(base, text) != _field(current, text)]
    assert len(changed) >= 10, changed


def test_document_fields_equal_base() -> None:
    """템플릿·예시·데모 계획서의 분야는 수정 전과 같다(기존 정답 사례가 깨지지 않는다)."""
    base = _need_base()
    got = {name: (_field(base, text), _field(current, text)) for name, text in document_inputs()}
    assert {k: v for k, v in got.items() if v[0] != v[1]} == {}
    assert got["tests/fixtures/plans/plan_elife_neuro.md"] == ("신경과학·뇌영상", "신경과학·뇌영상")


# 수정 전에도 신경과학이던 진짜 신경과학 구절(E3-L1x 검증 3-2절 + 인지 복합어 + E3-L1z 검증 발견 A). 수정 뒤에도 신경과학이어야 한다.
KNOWN_NEURO = (
    "fMRI BOLD signal을 측정한다.", "EEG 신호를 기록한다.", "뉴런 발화를 기록한다.", "신경세포 배양", "cognitive load task",
    "brain connectivity", "brains of mice", "neurons and neuronal activity", "neuroscience", "neuroimaging study",
    "뇌 영상", "뇌파", "대뇌 피질", "인지 과학", "인지 기능 저하", "신경 영상", "신경계 질환", "신경 활동", "신경 신호",
    "인지과제 분류", "경도인지장애 환자", "경도 인지장애", "사회인지기능 척도", "(인지 부하)", "인지심리학",
    "사회인지 기능", "경도인지 장애", "신경인지 기능", "사회인지 과제", "시각인지 능력",  # 검증 발견 A
)


@pytest.mark.parametrize("text", KNOWN_NEURO)
def test_known_neuroscience_phrases_stay_neuroscience(text: str) -> None:
    base = _need_base()
    assert _field(base, text) == "신경과학·뇌영상"  # 기준 커밋에서도 정답이던 사례만 둔다
    assert _field(current, text) == "신경과학·뇌영상"


# 정책 기대는 기준 모듈이나 현재 상수로 만들지 않고 대표 승인값으로 고정한다.
def policy_plan(length: int, *, padded: bool = False) -> PlanDocument:
    text = (
        "연구 목표는 배터리 전해액 예측이다.\n"
        "방법은 모델을 학습한다.\n"
        "데이터를 수집한다.\n"
        "정확도로 평가하고 기준선과 비교한다.\n"
    )
    text += "가" * (length - len(text))
    assert len(text) == length
    return PlanDocument.from_text("  " + text + "  " if padded else text, "policy-boundary")


@pytest.mark.parametrize("length,level,codes", [
    (299, "reject", ["too_short"]), (300, "warn", ["short"]),
    (301, "warn", ["short"]), (599, "warn", ["short"]),
    (600, "ok", []), (601, "ok", []),
])
@pytest.mark.parametrize("padded", [False, True])
def test_approved_policy_boundaries(length: int, level: str, codes: list[str], padded: bool) -> None:
    plan = policy_plan(length, padded=padded)
    rule = current.rule_fitness(plan)
    iq = rule["input_quality"]
    assert iq["metrics"]["length"] == length  # 앞뒤 공백 제외, 내부 공백 포함, 한글 가중치 없음
    assert iq["metrics"]["n_elements"] == rule["n_elements"] == 4
    assert iq["thresholds"]["min_chars"] == 300
    assert iq["thresholds"]["warn_chars"] == 600
    assert iq["level"] == level
    assert [r["code"] for r in iq["reasons"]] == codes
    assert iq["status"] == {"reject": "rejected_thin_input", "warn": "warn_short_input", "ok": "ok"}[level]
    assert iq["generator"] == "rule" and iq["source"] == "rule"
    assert rule["verdict"] == ("unfit" if length == 299 else "fit")
    assert rule["precheck"] == ("too_short" if length == 299 else None)
    if level == "reject":
        assert iq["message"] == (
            "입력이 300자 미만이라 연구계획서로 분석하지 않습니다. 연구 질문·방법·데이터·평가를 적어 주세요."
        )
    elif level == "warn":
        assert iq["message"].startswith("입력이 짧아 결과 신뢰도가 낮습니다")
    else:
        assert iq["message"] is None

    fallback = current.assess_fitness(plan, None)
    assert fallback["verdict"] == rule["verdict"]
    assert fallback["input_quality"] == iq
    assert fallback["decided_by"] == ("precheck" if level == "reject" else "rule_fallback")
    assert fallback["status"] == ("ok" if level == "reject" else "degraded")
    assert fallback["degraded_reason"] == (None if level == "reject" else "llm_unavailable: llm_call 없음")

    class CountingLLM(FixedLLM):
        calls = 0

        def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            return super().__call__(*args, **kwargs)

    llm = CountingLLM("research_plan")
    modeled = current.assess_fitness(plan, llm)
    assert llm.calls == (0 if length == 299 else 1)
    assert modeled["verdict"] == ("unfit" if length == 299 else "fit")
    assert modeled["decided_by"] == ("precheck" if length == 299 else "llm")


def test_classifications_unchanged_against_policy_reference() -> None:
    """251건을 제외 없이 승인된 정책 기준과 대조한다(규칙 판정과 모델/강등 분류)."""
    reference = policy_module()
    for name, text in corpus():
        plan = PlanDocument.from_text(text, "classification-regression")
        assert current.rule_fitness(plan)["verdict"] == reference.rule_fitness(plan)["verdict"], name
        for llm in (None, FixedLLM("research_plan"), FixedLLM("not_research_plan"), FixedLLM("uncertain")):
            before = reference.assess_fitness(plan, llm)
            after = current.assess_fitness(plan, llm)
            assert (after["verdict"], after["analyze"], after["is_research_plan"]) == (
                before["verdict"], before["analyze"], before["is_research_plan"]
            ), name


@pytest.mark.parametrize("mutation", ["rule_verdict", "model_verdict", "status", "notice", "quality_field"])
def test_policy_comparison_catches_output_mutations(monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    """현재 코드에 회귀를 주입해도 독립된 정책 기준은 같이 바뀌지 않는다."""
    if mutation == "rule_verdict":
        original = current.rule_fitness

        def changed_rule(plan: PlanDocument) -> dict[str, Any]:
            out = original(plan)
            out["verdict"] = "unfit" if out["verdict"] == "fit" else "fit"
            return out

        monkeypatch.setattr(current, "rule_fitness", changed_rule)
    else:
        original_assess = current.assess_fitness

        def changed_assess(*args: Any, **kwargs: Any) -> dict[str, Any]:
            out = original_assess(*args, **kwargs)
            if mutation == "model_verdict":
                if args[1] is not None:
                    out["verdict"] = "unfit" if out["verdict"] == "fit" else "fit"
                return out
            if mutation == "quality_field":
                out["input_quality"] = {**out["input_quality"], "metrics": {**out["input_quality"]["metrics"], "field": "오류"}}
            else:
                key = {"status": "status", "notice": "notice"}[mutation]
                out[key] = "회귀"
            return out

        monkeypatch.setattr(current, "assess_fitness", changed_assess)
    with pytest.raises(AssertionError, match="분야 밖 반환값"):
        test_non_field_outputs_equal_base()


@pytest.mark.parametrize("length,wrong_level", [(299, "warn"), (300, "reject"), (599, "ok"), (600, "warn")])
def test_boundary_checks_catch_policy_mutations(monkeypatch: pytest.MonkeyPatch, length: int, wrong_level: str) -> None:
    original = current.input_quality

    def changed_quality(*args: Any, **kwargs: Any) -> dict[str, Any]:
        out = original(*args, **kwargs)
        if out["metrics"]["length"] == length:
            out["level"] = wrong_level  # 상수는 그대로 두고 경계 판정만 잘못되게 한다
        return out

    monkeypatch.setattr(current, "input_quality", changed_quality)
    correct_level = {299: "reject", 300: "warn", 599: "warn", 600: "ok"}[length]
    correct_codes = {299: ["too_short"], 300: ["short"], 599: ["short"], 600: []}[length]
    with pytest.raises(AssertionError):
        test_approved_policy_boundaries(length, correct_level, correct_codes, False)
