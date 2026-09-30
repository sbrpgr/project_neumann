"""공용 fixture 로더. 모든 에픽 테스트가 쓴다.

    from tests.fixtures.loader import load_fixtures, plan_text
    fx = load_fixtures()
    fx.reviews[0].text, fx.excerpts[0].verify_against(fx.source_text(fx.excerpts[0]))

파일(이 폴더):
- works.jsonl(6) · reviews.jsonl(12) · decisions.jsonl(6) · excerpts.jsonl(12) · risk_tags.jsonl(12)
- risk_cards.jsonl(2) · premortem_result.json(plan.md 기준 결과 1건, UI·API 개발용)
- plans/: plan.md · plan_elife_neuro.md · plan_medimaging.md(기획 키트 원본 그대로) · negative_recipe.md(음성 대조)
내용은 전부 가짜다. 다시 만들려면 make_fixtures.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from neumann.models import Decision, Excerpt, PremortemResult, ReviewEvent, RiskCard, RiskTag, Work

FIXTURES_DIR = Path(__file__).resolve().parent
PLANS_DIR = FIXTURES_DIR / "plans"
DEMO_PLANS = ("plan.md", "plan_elife_neuro.md", "plan_medimaging.md")
NEGATIVE_PLAN = "negative_recipe.md"

M = TypeVar("M", bound=BaseModel)


def read_jsonl(name: str, model: type[M]) -> list[M]:
    path = FIXTURES_DIR / name
    return [model.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def plan_text(name: str = "plan.md") -> str:
    return (PLANS_DIR / name).read_text(encoding="utf-8")


@dataclass(frozen=True)
class Fixtures:
    works: list[Work]
    reviews: list[ReviewEvent]
    decisions: list[Decision]
    excerpts: list[Excerpt]
    risk_tags: list[RiskTag]
    risk_cards: list[RiskCard]
    premortem_result: PremortemResult

    def source_text(self, ex: Excerpt) -> str:
        """Excerpt가 가리키는 원문(저장된 정규화 텍스트)."""
        if ex.source_kind == "review":
            return next(r.text for r in self.reviews if r.review_id == ex.source_id)
        if ex.source_kind == "decision":
            text = next(d.text for d in self.decisions if d.decision_id == ex.source_id)
            assert text is not None
            return text
        raise KeyError(f"fixture에 없는 source_kind: {ex.source_kind}")

    def excerpt(self, excerpt_id: str) -> Excerpt:
        return next(e for e in self.excerpts if e.excerpt_id == excerpt_id)


@lru_cache(maxsize=1)
def load_fixtures() -> Fixtures:
    return Fixtures(
        works=read_jsonl("works.jsonl", Work),
        reviews=read_jsonl("reviews.jsonl", ReviewEvent),
        decisions=read_jsonl("decisions.jsonl", Decision),
        excerpts=read_jsonl("excerpts.jsonl", Excerpt),
        risk_tags=read_jsonl("risk_tags.jsonl", RiskTag),
        risk_cards=read_jsonl("risk_cards.jsonl", RiskCard),
        premortem_result=PremortemResult.model_validate(
            json.loads((FIXTURES_DIR / "premortem_result.json").read_text(encoding="utf-8"))
        ),
    )


__all__ = ["DEMO_PLANS", "FIXTURES_DIR", "Fixtures", "NEGATIVE_PLAN", "PLANS_DIR", "load_fixtures", "plan_text", "read_jsonl"]
