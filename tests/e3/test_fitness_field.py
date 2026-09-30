"""E3-L1x: 규칙 판정 분야(field) — 인공 신경망·신경 연산자를 신경과학으로 분류하지 않는다(실제 API 없음).

버그: 영어 `neur\\w*`가 neural을, 한국어 "신경"이 신경망·신경 연산자를 잡아 AI for Science 계획서
(예: Fourier Neural Operator PDE 대리모델)가 "신경과학·뇌영상"으로 분류됐다.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from neumann.analyze.fitness import _FIELDS, _NEURO_EN, _NEURO_KO, _line_hits, assess_fitness, rule_fitness
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


# ── E3-L1z: "~인지" 어미, 영어 약어 + 한글 조사, neuromorphic·neuro-symbolic ─────────────


@pytest.mark.parametrize(
    "text",
    [
        "효과적인지 과제별로 검증한다.",  # E3-L1x 검증에서 남은 오탐
        "나은 것인지 기능 단위로 분해한다.",
        "누출이 없는 분할인지 과제마다 확인한다.",
        "기준선보다 나은지, 충분한 것인지 능력 범위 안에서 본다.",
        "타당한 설계인지 부하 시험으로 확인한다.",
        "이것이 문화인지 기능인지 따진다.",  # 접두어 목록 밖(문화)의 "-ㄴ지"는 그대로 뺀다
        "위험을 인지하고 대응 절차를 둔다.",
    ],
)
def test_korean_ending_inji_is_not_neuroscience(text: str) -> None:
    """어미 "-ㄴ지"의 "인지" 뒤에 과제·기능·능력·부하가 띄어서 와도 신경과학 표지가 아니다."""
    plan = _plan(text)
    assert _neuro_terms(plan) == []
    assert rule_fitness(plan)["field"] != NEURO


@pytest.mark.parametrize(
    ("text", "expected_terms"),
    [
        ("인지 과제 수행 중 반응 시간을 잰다.", {"인지 과제"}),
        ("fMRI 기반 인지과제 분류 모델을 만든다.", {"fmri", "인지과제"}),
        ("경도인지장애 환자의 기억 검사 점수를 본다.", {"인지장애"}),
        ("경도 인지장애와 치매를 구분한다.", {"인지장애"}),
        ("노인의 인지 기능 저하를 추적한다.", {"인지 기능"}),
        ("과제 난이도(인지 부하)를 세 단계로 둔다.", {"인지 부하"}),
        ("사회인지기능 척도로 평가한다.", {"인지기능"}),
        ("인지심리학 실험 설계를 따른다.", {"인지심리"}),
        # E3-L1z 검증 발견 A: 인지 접두어 뒤에 띄어 쓴 복합어(main에서는 잡혔다)
        ("사회인지 기능 척도로 평가한다.", {"인지 기능"}),
        ("경도인지 장애 환자를 모은다.", {"인지 장애"}),
        ("신경인지 기능 검사를 한다.", {"인지 기능"}),
        ("사회인지 과제 중 시선을 추적한다.", {"인지 과제"}),
        ("시각인지 능력을 비교한다.", {"인지 능력"}),
    ],
)
def test_cognition_compounds_stay_neuroscience(text: str, expected_terms: set[str]) -> None:
    """낱말 첫머리의 "인지 ~"와 붙여 쓴 복합어(경도인지장애·사회인지기능)는 그대로 신경과학 표지다."""
    plan = _plan(text)
    assert set(_neuro_terms(plan)) == expected_terms
    assert rule_fitness(plan)["field"] == NEURO


@pytest.mark.parametrize(
    ("text", "field", "expected_terms"),
    [
        ("EEG와 fMRI로 작업기억 과제 중 신호를 기록한다.", NEURO, {"eeg", "fmri"}),
        ("전기 신호는 EEG를, 혈류는 fMRI를 쓴다.", NEURO, {"eeg", "fmri"}),
        ("쥐 brain을 절편으로 만들어 neuroimaging을 한다.", NEURO, {"brain", "neuroimaging"}),
        ("DNA와 RNA를 시퀀싱해 발현량을 잰다.", "생명과학·생물정보", {"dna", "rna"}),
        ("LLM으로 초록을 요약하고 NLP를 적용한다.", "자연어처리", {"llm", "nlp"}),
        ("x-ray로 찍은 흉부 사진을 쓴다.", "의료·의료영상", {"x-ray"}),
        ("plasma를 자기장으로 가둔다.", "물리·공학", {"plasma"}),
        ("EEG_data 폴더의 기록을 쓴다.", NEURO, {"eeg"}),  # 밑줄은 로마자·숫자가 아니다
    ],
)
def test_english_term_followed_by_korean_particle(text: str, field: str, expected_terms: set[str]) -> None:
    """영어 약어·낱말 바로 뒤에 한글 조사가 붙어도 분야 표지로 잡고, 표지 문자열에 조사를 넣지 않는다."""
    plan = _plan(text)
    [(ko, en)] = [(ko, en) for name, ko, en in _FIELDS if name == field]
    got = {t for ln in plan.lines for t in _line_hits(ln.text, ko, en)}
    assert got == expected_terms
    assert rule_fitness(plan)["field"] == field


@pytest.mark.parametrize(
    "text",
    [
        "brainstorming과 rebranding을 논의한다.",  # 로마자 낱말 한가운데
        "EEGs2 같은 식별자는 표지가 아니다.",
        "neuronal이 아니라 aneuronal이라는 가상의 낱말.",
    ],
)
def test_english_terms_inside_latin_words_are_not_hits(text: str) -> None:
    hits = _neuro_terms(_plan(text))
    assert "brain" not in hits and "eeg" not in hits and "aneuronal" not in hits
    assert hits in ([], ["neuronal"])  # 셋째 줄의 독립 낱말 neuronal만 잡힌다


@pytest.mark.parametrize(
    "text",
    [
        "neuromorphic hardware accelerator에 올린다.",
        "Neuromorphic 칩으로 추론 전력을 줄인다.",
        "neuro-symbolic reasoning으로 규칙을 배운다.",
        "Neuro-Symbolic AI 기법을 기준선으로 둔다.",
        "neurosymbolic program synthesis를 쓴다.",
        "neuro symbolic 모델과 비교한다.",
    ],
)
def test_neuromorphic_and_neuro_symbolic_are_ai_terms(text: str) -> None:
    plan = _plan(text)
    assert _neuro_terms(plan) == []
    assert rule_fitness(plan)["field"] != NEURO


@pytest.mark.parametrize(
    ("text", "expected_terms"),
    [
        ("neuroscience 공개 데이터를 쓴다.", {"neuroscience"}),
        ("We record neurons and neuronal oscillations.", {"neurons", "neuronal"}),
        ("neuro-oncology 코호트의 MRI를 분석한다.", {"neuro"}),
        ("cognitive load를 과제별로 바꾼다.", {"cognitive"}),
    ],
)
def test_other_neuro_terms_still_neuroscience(text: str, expected_terms: set[str]) -> None:
    plan = _plan(text)
    assert set(_neuro_terms(plan)) == expected_terms
    assert rule_fitness(plan)["field"] == NEURO


# ── 적대 입력: 새로 넣거나 바꾼 정규식은 10만 자에서 0.2초 미만(ReDoS 금지) ─────────────

_ADVERSARIAL_UNITS = (
    "인지", "인지 ", "가인지 ", "인지\u3000", "인지과", "신경 ", "뇌", "가", "a", "a가", "neuro", "neuro-", "neuro ",
    "neurosymboli", "neuromorphi", "neuro-symboli", "cognit", "eeg와", "x-", "x-ra", "brain", "_", "9",
    "사회인지 ", "경도인지", "사회인지　", "사회",
)


def _adversarial_inputs() -> list[tuple[str, str]]:
    n = 100_000
    return [(u, (u * (n // len(u) + 1))[:n]) for u in _ADVERSARIAL_UNITS]


def _changed_patterns() -> list[tuple[str, re.Pattern[str]]]:
    pats = [("neuro_ko", _NEURO_KO), ("neuro_en", _NEURO_EN)]
    pats += [(f"field_en:{name}", en) for name, _ko, en in _FIELDS]
    return pats


@pytest.mark.parametrize(("pname", "pattern"), _changed_patterns(), ids=[p for p, _ in _changed_patterns()])
def test_changed_patterns_are_linear_on_adversarial_input(pname: str, pattern: re.Pattern[str]) -> None:
    for unit, text in _adversarial_inputs():
        assert len(text) == 100_000
        t0 = time.perf_counter()
        n = sum(1 for _ in pattern.finditer(text))
        dt = time.perf_counter() - t0
        assert dt < 0.2, f"{pname}: 반복 단위 {unit!r} 10만 자에서 {dt:.3f}s ({n}건)"
