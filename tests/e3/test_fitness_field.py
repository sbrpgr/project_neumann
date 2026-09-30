"""E3-L1x: 규칙 판정 분야(field) — 인공 신경망·신경 연산자를 신경과학으로 분류하지 않는다(실제 API 없음).

버그: 영어 `neur\\w*`가 neural을, 한국어 "신경"이 신경망·신경 연산자를 잡아 AI for Science 계획서
(예: Fourier Neural Operator PDE 대리모델)가 "신경과학·뇌영상"으로 분류됐다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neumann.analyze.fitness import _FIELDS, _line_hits, assess_fitness, rule_fitness
from neumann.models import PlanDocument

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "src" / "neumann" / "api" / "templates"
NEURO = "신경과학·뇌영상"

# 카탈로그 도메인(E4) → 규칙 분야로 허용하는 값
DOMAIN_FIELDS = {
    "소재·화학·분자": {"재료·화학"},
    "단백질·생물·신약": {"생명과학·생물정보"},
    "물리·PDE·기후": {"물리·공학", "기후·지구과학"},
}


def _plan(text: str) -> PlanDocument:
    return PlanDocument.from_text(text, "sess-test")


def _neuro_terms(plan: PlanDocument) -> list[str]:
    """계획서 전체에서 신경과학 분야 표지로 잡힌 말(분야 점수와 같은 규칙)."""
    [(ko, en)] = [(ko, en) for name, ko, en in _FIELDS if name == NEURO]
    return sorted({t for ln in plan.lines for t in _line_hits(ln.text, ko, en)})


# ── 신경 연산자·AI 방법 계획서는 신경과학이 아니다 ─────────────────────────


@pytest.mark.parametrize(
    "rel",
    ["pde_operator.md", "examples/neural_operator_weather.md", "protein_binding.md", "molecule_reaction.md"],
)
def test_ai_for_science_documents_are_not_neuroscience(rel: str) -> None:
    plan = _plan((TEMPLATES / rel).read_text(encoding="utf-8"))
    assert _neuro_terms(plan) == []  # 한 줄도 신경과학 표지로 잡히지 않는다(점수 동률 뒤집힘도 막는다)
    r = rule_fitness(plan)
    assert r["field"] is not None and r["field"] != NEURO


def test_pde_operator_template_is_physics() -> None:
    """고치기 전에는 신경과학 3줄·물리 3줄 동률에서 신경과학이 먼저 나와 이겼다."""
    plan = _plan((TEMPLATES / "pde_operator.md").read_text(encoding="utf-8"))
    assert rule_fitness(plan)["field"] == "물리·공학"


def test_neural_operator_example_field_on_rule_fallback() -> None:
    """astra가 실패해 규칙으로 강등돼도 화면에 나가는 분야가 신경과학이 아니다."""
    plan = _plan((TEMPLATES / "examples" / "neural_operator_weather.md").read_text(encoding="utf-8"))
    r = assess_fitness(plan, None)
    assert r["status"] == "degraded" and r["generator"] == "rule"
    assert r["field"] == "기후·지구과학"


def _catalog_docs() -> list:
    """카탈로그의 템플릿(파일명은 templates 폴더 기준)과 예시(경로는 저장소 기준)."""
    catalog = json.loads((TEMPLATES / "catalog.json").read_text(encoding="utf-8"))
    docs = [pytest.param(TEMPLATES / t["file"], t["domain"], id=t["id"]) for t in catalog["templates"]]
    docs += [pytest.param(ROOT / e["path"], e["domain"], id=e["id"]) for e in catalog["examples"]]
    return docs


@pytest.mark.parametrize(("path", "domain"), _catalog_docs())
def test_catalog_documents_field_matches_domain(path: Path, domain: str) -> None:
    """입력 카탈로그의 템플릿·예시가 규칙 판정에서 자기 도메인에 맞는 분야로 나온다."""
    field = rule_fitness(_plan(path.read_text(encoding="utf-8")))["field"]
    assert domain in DOMAIN_FIELDS, f"카탈로그에 새 도메인 {domain!r}: DOMAIN_FIELDS에 허용 분야를 추가하라"
    assert field in DOMAIN_FIELDS[domain], f"{path.name}: {field!r} (도메인 {domain})"


@pytest.mark.parametrize(
    "text",
    [
        "Fourier Neural Operator로 Navier-Stokes 해를 학습한다.",
        "We train a Graph Neural Network surrogate.",
        "physics-informed neural networks and a neural operator baseline",
        "그래프 신경망으로 이온전도도를 예측한다.",
        "합성곱 신경망과 심층신경망을 비교한다.",
        "기존 신경 연산자와 신경연산자 변형을 기준선으로 둔다.",
        "다층 신경회로망과 신경 회로망 모델을 쓴다.",
        "이 비교가 공정한 것인지, 누출이 없는 분할인지 확인한다.",  # "~인지" 어미
        "뇌우와 집중호우를 포함한 기상 예측을 평가한다.",  # 뇌우(기상)
    ],
)
def test_ai_method_and_everyday_terms_are_not_neuroscience(text: str) -> None:
    plan = _plan(text)
    assert _neuro_terms(plan) == []
    assert rule_fitness(plan)["field"] != NEURO


# ── 진짜 신경과학 계획서는 그대로 신경과학 ─────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected_terms"),
    [
        (
            "기능적 자기공명영상(fMRI)으로 작업기억 과제 중 전전두엽 뇌 활성화를 측정한다.\n"
            "참가자 40명의 EEG 신호와 fMRI BOLD 신호를 함께 수집해 인지 과제 정확도와 신경 활동의 상관을 분석한다.\n"
            "피험자 단위 교차검증으로 분류 정확도를 평가한다.",
            {"fmri", "eeg", "뇌", "인지 과제", "신경 활동"},
        ),
        (
            "We record 64-channel EEG from 30 participants during a cognitive load task.\n"
            "We model neuronal oscillations and brain connectivity to predict working-memory performance.\n"
            "We evaluate classification accuracy with leave-one-subject-out cross-validation.",
            {"eeg", "cognitive", "neuronal", "brain"},
        ),
        (
            "생쥐 해마 신경세포의 칼슘 영상으로 뉴런 발화 패턴을 기록한다.\n"
            "신경과학 공개 데이터와 비교해 뇌 부위별 차이를 분석한다.",
            {"신경세포", "뉴런", "신경과학", "뇌"},
        ),
    ],
)
def test_real_neuroscience_plans_stay_neuroscience(text: str, expected_terms: set[str]) -> None:
    plan = _plan(text)
    assert set(_neuro_terms(plan)) == expected_terms
    assert rule_fitness(plan)["field"] == NEURO
