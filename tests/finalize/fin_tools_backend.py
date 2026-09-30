"""FIN-TOOLS 테스트용 근거 백엔드: 공용 fixture(가짜 논문 6편)로 임시 데이터 폴더를 만들고 MCP 서버 백엔드를 그대로 쓴다."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neumann.api.mcp_server import build_default_backend
from neumann.models import PostStatus, PostStatusKind, Provenance, sha256_text
from tests.fixtures.loader import load_fixtures

RETRACTED_DOI = "10.9999/fake.0001"
ACCESSED = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)


def _write_jsonl(path: Path, models: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for m in models:
            f.write(json.dumps(m.model_dump(mode="json"), ensure_ascii=False) + "\n")


def build_backend(root: Path) -> Any:
    fx = load_fixtures()
    index_dir = root / "index"
    try:
        from neumann.index.store import IndexStore
    except ImportError:
        _write_jsonl(index_dir / "works.jsonl", fx.works)
        _write_jsonl(index_dir / "reviews.jsonl", fx.reviews)
    else:
        IndexStore.from_corpus(fx.works, fx.reviews).save(index_dir)  # 임베딩 없이(어휘 검색)
    _write_jsonl(root / "processed" / "decisions.jsonl", fx.decisions)
    rows = []
    for psid, kind, notice in [("rw:fake-1", PostStatusKind.retraction, "10.9999/fake.notice1")]:
        rows.append(PostStatus(
            post_status_id=psid, kind=kind, target_doi=RETRACTED_DOI, notice_doi=notice,
            reason_codes=["Concerns/Issues about Data"], url=f"https://doi.org/{notice}",
            provenance=Provenance(source="retraction_watch", source_url="https://example.org/fake-rw/rw.csv",
                                  accessed_at=ACCESSED, content_sha256=sha256_text(psid),
                                  license="fixture-fake-data", api_version="rw-csv:fixture"),
        ))
    _write_jsonl(root / "processed" / "retraction.jsonl", rows)
    return build_default_backend(root, index_dir)
