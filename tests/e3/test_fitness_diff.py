"""E3-L1z: 규칙 판정 차등 검사 — 분야(field)를 뺀 반환값이 기준 커밋(main)과 같다(실제 API 없음).

E3-L1z는 분야 표지만 고친다(인지 복합어, 영어 약어+한글 조사, neuromorphic·neuro-symbolic). 판정
(fit·unfit·uncertain), 요소별 줄 번호, 무관 표지, 사유, 강등 표기는 한 글자도 바뀌면 안 된다.
기준 커밋의 `fitness.py`를 `git show`로 읽어 따로 올리고, 같은 입력(템플릿·예시·데모 계획서 + 무작위 240건)을
두 판에 넣어 비교한다. git이나 기준 커밋이 없는 환경(얕은 복제 등)에서는 건너뛴다.

이후 과제가 판정 규칙(요소·무관 사전, 판정 분기)을 일부러 바꾸면 이 검사는 실패한다. 그때는 그 과제의 기준
커밋으로 `BASE_REV`를 옮기고 보고서에 적는다.
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
N_RANDOM = 240
SEED = 20260930


@functools.lru_cache(maxsize=1)
def base_module() -> types.ModuleType | None:
    """기준 커밋의 fitness.py를 별도 모듈로 올린다. git·커밋이 없으면 None."""
    try:
        proc = subprocess.run(
            ["git", "show", f"{BASE_REV}:src/neumann/analyze/fitness.py"],
            cwd=ROOT, capture_output=True, check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    mod = types.ModuleType("neumann_fitness_base")
    exec(compile(proc.stdout.decode("utf-8"), f"{BASE_REV}:fitness.py", "exec"), mod.__dict__)  # noqa: S102
    return mod


def _need_base() -> types.ModuleType:
    mod = base_module()
    if mod is None:
        pytest.skip(f"git 또는 기준 커밋 {BASE_REV}이 없다")
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


def _without_field(result: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in result.items() if k not in ("field", "elapsed_s")}
    if isinstance(out.get("rule"), dict):
        out["rule"] = {k: v for k, v in out["rule"].items() if k != "field"}
    return out


def outcomes(mod: types.ModuleType, text: str) -> dict[str, Any]:
    """한 입력의 규칙 판정·강등 판정·모델 판정 3종(분야 뺌)과 분야."""
    plan = PlanDocument.from_text(text, "sess-e3-l1z")
    rule = mod.rule_fitness(plan)
    runs = {"rule": _without_field(rule), "fallback": _without_field(mod.assess_fitness(plan, None))}
    for v in ("research_plan", "not_research_plan", "uncertain"):
        runs[f"llm_{v}"] = _without_field(mod.assess_fitness(plan, FixedLLM(v)))
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
    """분야를 뺀 반환값(규칙·강등·모델 판정 3종)이 기준 커밋과 글자 단위로 같다."""
    base = _need_base()
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
