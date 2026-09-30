"""E3-L2r 테스트 공용: fixture 결과 + 가짜 기록 저장소(채택 논문의 저자 답변·결정)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from neumann.analyze.revise_records import MemoryRecordStore
from neumann.models import AuthorResponse, Provenance, sha256_text
from tests.fixtures.loader import load_fixtures

ACCEPTED_WORK = "fixture:gnn-002"  # fixture decisions: accept_poster
RESPONSE_TEXT = (
    "We thank the reviewer for pointing out the leakage concern. "
    "We re-ran all experiments with a scaffold split and removed near-duplicate compositions before splitting. "
    "The random split results are kept in the appendix for comparison."
)


def fake_response(work_id: str = ACCEPTED_WORK, response_id: str = "resp-fx-001", text: str = RESPONSE_TEXT) -> AuthorResponse:
    url = f"https://example.org/fake-venue/forum?id={work_id.split(':')[-1]}&noteId={response_id}"
    prov = Provenance(source="fixture", source_url=url, accessed_at=datetime(2026, 9, 30, 9, 0, tzinfo=UTC),
                      content_sha256=sha256_text(text), license="fixture-fake-data")
    return AuthorResponse(provenance=prov, response_id=response_id, work_id=work_id, text=text, url=url)


def make_store(*, with_accepted_response: bool = True, **kw: Any) -> MemoryRecordStore:
    fx = load_fixtures()
    responses = [fake_response()] if with_accepted_response else []
    return MemoryRecordStore(decisions=fx.decisions, responses=responses, reviews=fx.reviews, works=fx.works,
                             source="fixture", **kw)


class FakeCall:
    """가짜 llm_call(test_review와 같은 모양). generator 속성이 있어야 표기가 정해진다."""

    def __init__(self, response: Any = None, *, raises: Exception | None = None, generator: str = "astra",
                 model: str = "fake-model") -> None:
        self.response = response
        self.raises = raises
        self.calls: list[dict[str, Any]] = []
        self.generator = generator
        self.model = model
        self.last_error: str | None = None

    def __call__(self, schema, instructions, input, *, effort):  # noqa: A002
        self.calls.append({"schema": schema, "instructions": instructions, "input": input, "effort": effort})
        if self.raises:
            raise self.raises
        return self.response(schema, input) if callable(self.response) else self.response
