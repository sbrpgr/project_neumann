"""E4-L2b MCP 서버 테스트.

1) 공식 SDK 클라이언트(`mcp.Client` + stdio)로 `python -m neumann.api.mcp_server`를 실제 하위 프로세스로 띄워
   도구 목록 3개, 도구별 결과 형식, 없는 id·잘못된 입력 처리를 본다. 데이터는 공용 fixture로 만든 임시 데이터 폴더다.
2) 같은 서버를 프로세스 안에서 붙여(Client(server)) 신원 필드 차단·데이터 누락 표기·어댑터를 본다.

실제 색인·API를 부르지 않는다. 임시 색인은 E2 색인 모듈이 있으면 그것으로(임베딩 없이) 만들고, 없으면
E2 디스크 형식(works.jsonl·reviews.jsonl)으로 직접 쓴다 — 서버의 얇은 어댑터가 그대로 읽는다.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from neumann.api import mcp_server as ms
from neumann.models import (
    IDENTITY_TOKENS,
    AuthorResponse,
    PostStatus,
    PostStatusKind,
    Provenance,
    ReviewEvent,
    sha256_text,
)
from tests.fixtures.loader import load_fixtures, plan_text

ROOT = Path(__file__).resolve().parents[2]
FAKE_DOI = "10.9999/fake.0001"
FAKE_DOI_NONE = "10.9999/fake.none"
ACCESSED = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)


# ── 임시 데이터 폴더(fixture) ─────────────────────────────────────────────


def _prov(url: str, body: str) -> Provenance:
    return Provenance(
        source="fixture",
        source_url=url,
        accessed_at=ACCESSED,
        content_sha256=sha256_text(body),
        license="fixture-fake-data",
        api_version="fixture-v1",
    )


def _responses() -> list[AuthorResponse]:
    texts = [
        ("resp-gnn-001-a", "rev-gnn-001-a", "We added a scaffold split in Table 3; MAE rises from 0.41 to 0.58 as expected."),
        ("resp-gnn-001-b", None, "General response: we thank the reviewers and summarize the revisions below. " * 12),
    ]
    out = []
    for rid, review_id, text in texts:
        url = f"https://example.org/fake-venue/forum?id=gnn-001&noteId={rid}"
        out.append(
            AuthorResponse(
                response_id=rid, work_id="fixture:gnn-001", text=text, review_id=review_id, url=url, round=1,
                provenance=_prov(url, text),
            )
        )
    return out


def _post_statuses() -> list[PostStatus]:
    rows = [
        ("rw:fake-1", PostStatusKind.retraction, "10.9999/fake.notice1", ["Concerns/Issues about Data", "Unreliable Results"]),
        ("rw:fake-2", PostStatusKind.correction, "10.9999/fake.notice2", ["Error in Figure"]),
    ]
    out = []
    for psid, kind, notice, reasons in rows:
        out.append(
            PostStatus(
                post_status_id=psid, kind=kind, target_doi=FAKE_DOI, notice_doi=notice, reason_codes=reasons,
                url=f"https://doi.org/{notice}",
                provenance=Provenance(
                    source="retraction_watch", source_url="https://example.org/fake-rw/retraction_watch.csv",
                    accessed_at=ACCESSED, content_sha256=sha256_text(psid), license="fixture-fake-data",
                    api_version="rw-csv:fixture",
                ),
            )
        )
    return out


def _write_jsonl(path: Path, models: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for m in models:
            f.write(json.dumps(m.model_dump(mode="json"), ensure_ascii=False) + "\n")


def _write_index(index_dir: Path) -> str:
    fx = load_fixtures()
    try:
        from neumann.index.store import IndexStore
    except ImportError:
        _write_jsonl(index_dir / "works.jsonl", fx.works)
        _write_jsonl(index_dir / "reviews.jsonl", fx.reviews)
        return "files"
    IndexStore.from_corpus(fx.works, fx.reviews).save(index_dir)  # 임베딩 없이(어휘 검색만)
    return "e2"


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("mcp_data")
    _write_index(d / "index")
    fx = load_fixtures()
    _write_jsonl(d / "processed" / "decisions.jsonl", fx.decisions)
    _write_jsonl(d / "processed" / "author_responses.jsonl", _responses())
    _write_jsonl(d / "processed" / "retraction.jsonl", _post_statuses())
    (d / "processed" / "retraction_manifest.json").write_text(
        json.dumps(
            {
                "citation": "FAKE citation for tests",
                "dataset_home": "https://example.org/fake-rw",
                "license": "fixture-fake-data",
                "snapshot_generated": "2099-01-01",
            }
        ),
        encoding="utf-8",
    )
    return d


# ── 1) stdio: 실제 하위 프로세스 ─────────────────────────────────────────


async def _stdio_scenario(params: StdioServerParameters, errlog: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    async with Client(stdio_client(params, errlog=errlog), read_timeout_seconds=120) as c:
        out["tools"] = (await c.list_tools()).tools
        call = c.call_tool
        out["search"] = await call("search_similar_works", {"query": "liver tumor segmentation CT", "k": 3})
        out["search_default_k"] = await call("search_similar_works", {"query": "molecular property prediction"})
        out["search_plan_body"] = await call("search_similar_works", {"query": plan_text("plan.md")})
        out["search_k0"] = await call("search_similar_works", {"query": "segmentation", "k": 0})
        out["search_empty"] = await call("search_similar_works", {"query": "   "})
        out["records"] = await call("get_review_records", {"work_id": "fixture:gnn-001"})
        out["records_missing"] = await call("get_review_records", {"work_id": "fixture:does-not-exist"})
        out["post"] = await call("get_post_status", {"doi": "https://doi.org/10.9999/FAKE.0001"})
        out["post_none"] = await call("get_post_status", {"doi": FAKE_DOI_NONE})
        out["post_bad"] = await call("get_post_status", {"doi": "not a doi"})
    return out


@pytest.fixture(scope="module")
def stdio(data_dir: Path) -> dict[str, Any]:
    env = {
        "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)]),
        "PYTHONIOENCODING": "utf-8",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "NEUMANN_LLM_PROVIDER": "mock",
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "neumann.api.mcp_server", "--data-dir", str(data_dir), "--index-dir", str(data_dir / "index"),
              "--no-warmup"],
        env=env,
        cwd=str(ROOT),
    )
    log_path = data_dir / "server_stderr.log"
    with log_path.open("w", encoding="utf-8") as errlog:
        out = asyncio.run(_stdio_scenario(params, errlog))
    out["stderr"] = log_path.read_text(encoding="utf-8", errors="replace")
    return out


def _text(res: Any) -> str:
    return "\n".join(getattr(b, "text", "") for b in res.content)


def _has_module(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except ImportError:
        return False


def test_mcp_lists_three_read_only_tools(stdio: dict[str, Any]) -> None:
    tools = {t.name: t for t in stdio["tools"]}
    assert sorted(tools) == sorted(ms.TOOL_NAMES), stdio["stderr"][-2000:]
    for t in tools.values():
        assert t.annotations is not None and t.annotations.read_only_hint is True
        assert t.annotations.destructive_hint is False and t.annotations.open_world_hint is False
        assert t.output_schema and t.output_schema.get("type") == "object"
        assert t.description
    assert set(tools["search_similar_works"].input_schema["properties"]) == {"query", "k"}
    assert tools["search_similar_works"].input_schema["required"] == ["query"]
    assert set(tools["get_review_records"].input_schema["properties"]) == {"work_id"}
    assert set(tools["get_post_status"].input_schema["properties"]) == {"doi"}


def test_mcp_search_result_shape(stdio: dict[str, Any]) -> None:
    res = stdio["search"]
    assert not res.is_error, _text(res)
    sc = res.structured_content
    assert sc["query"] == "liver tumor segmentation CT" and sc["k"] == 3
    assert 1 <= sc["n_hits"] <= 3 and sc["n_hits"] == len(sc["hits"])
    assert sc["hits"][0]["work_id"] == "fixture:seg-001"  # 제목에 liver·tumor·segmentation·CT
    fx = {w.work_id: w for w in load_fixtures().works}
    scores = [h["score"] for h in sc["hits"]]
    assert scores == sorted(scores, reverse=True)
    for h in sc["hits"]:
        w = fx[h["work_id"]]
        assert h["title"] == w.title and h["url"] == w.url and h["source_url"] == w.provenance.source_url
        assert h["url"].startswith("https://")
        for key in ("score", "dense", "lexical"):
            assert 0.0 <= h[key] <= 1.0
        assert h["matched_query"] == "liver tumor segmentation CT"
    # 임시 색인에는 임베딩이 없다 → 강등을 숨기지 않고 표시해야 한다.
    # E2 색인 모듈이 있으면 그 검색(어휘만), 없으면 서버의 파일 어댑터가 돈다.
    assert sc["backend"] == ("lexical_only" if _has_module("neumann.index.search") else "adapter_token_overlap")
    assert sc["degraded"] is True and sc["reason"]
    # 텍스트 콘텐츠도 같은 JSON이다(구조화 출력을 못 읽는 클라이언트용)
    assert json.loads(_text(res))["hits"][0]["work_id"] == "fixture:seg-001"


def test_mcp_search_default_k_and_input_rejections(stdio: dict[str, Any]) -> None:
    ok = stdio["search_default_k"]
    assert not ok.is_error and ok.structured_content["k"] == ms.DEFAULT_K
    assert {h["work_id"] for h in ok.structured_content["hits"]} >= {"fixture:gnn-001"}
    body = stdio["search_plan_body"]
    assert len(plan_text("plan.md")) > ms.MAX_QUERY_CHARS
    assert body.is_error and "계획서 본문" in _text(body)
    assert stdio["search_k0"].is_error and "k" in _text(stdio["search_k0"])
    assert stdio["search_empty"].is_error


def test_mcp_review_records_shape(stdio: dict[str, Any]) -> None:
    res = stdio["records"]
    assert not res.is_error, _text(res)
    sc = res.structured_content
    fx = load_fixtures()
    work = next(w for w in fx.works if w.work_id == "fixture:gnn-001")
    assert sc["work"]["work_id"] == work.work_id and sc["work"]["url"] == work.url
    reviews = [r for r in fx.reviews if r.work_id == work.work_id]
    assert sc["n_reviews"] == len(reviews) == len(sc["reviews"]) == 2
    by_id = {r.review_id: r for r in reviews}
    for rec in sc["reviews"]:
        src = by_id[rec["review_id"]]
        assert rec["url"] == src.url and rec["source_url"] == src.provenance.source_url
        assert src.text.startswith(rec["text_head"]) and rec["text_head"]  # 원문 앞부분 글자 그대로
        assert rec["text_chars"] == len(src.text) and rec["text_sha256"] == sha256_text(src.text)
        assert rec["truncated"] == (len(src.text) > ms.HEAD_CHARS)
        assert rec["kind"] == "official_review"
    # 저자 답변 2건(하나는 600자 넘어 잘림), 결정 1건
    assert sc["n_responses"] == 2
    long = next(r for r in sc["responses"] if r["response_id"] == "resp-gnn-001-b")
    assert long["truncated"] is True and len(long["text_head"]) == ms.HEAD_CHARS and long["review_id"] is None
    assert sc["n_decisions"] == 1
    dec = sc["decisions"][0]
    assert dec["outcome"] == "reject" and dec["outcome_raw"] and dec["url"].startswith("https://")
    for rec in sc["reviews"] + sc["responses"] + sc["decisions"]:
        assert rec["url"].startswith("https://") and rec["source_url"].startswith("https://")


def test_mcp_review_records_unknown_id(stdio: dict[str, Any]) -> None:
    res = stdio["records_missing"]
    assert res.is_error
    assert "fixture:does-not-exist" in _text(res) and "색인에 없다" in _text(res)
    assert not res.structured_content


def test_mcp_post_status_shape_and_missing(stdio: dict[str, Any]) -> None:
    res = stdio["post"]
    assert not res.is_error, _text(res)
    sc = res.structured_content
    assert sc["doi"] == FAKE_DOI and sc["status"] == "found" and sc["n_records"] == 2
    kinds = {r["kind"] for r in sc["records"]}
    assert kinds == {"retraction", "correction"}
    for r in sc["records"]:
        assert r["target_doi"] == FAKE_DOI
        assert r["notice_url"] == f"https://doi.org/{r['notice_doi']}"
        assert r["source_url"].startswith("https://") and r["reason_codes"]
    assert sc["citation"] == "FAKE citation for tests" and sc["dataset_url"] == "https://example.org/fake-rw"
    assert sc["backend"] == (
        "neumann.sources.retraction" if _has_module("neumann.sources.retraction") else "adapter:processed/retraction.jsonl"
    )
    none = stdio["post_none"]
    assert not none.is_error
    assert none.structured_content["status"] == "no_record" and none.structured_content["records"] == []
    bad = stdio["post_bad"]
    assert bad.is_error and "DOI" in _text(bad)


def test_mcp_outputs_have_no_identity_keys(stdio: dict[str, Any]) -> None:
    for key in ("search", "records", "post"):
        for k in _all_keys(stdio[key].structured_content):
            low = k.lower()
            assert not any(tok in low for tok in IDENTITY_TOKENS), (key, k)
            assert "pseudonym" not in low and "reviewer" not in low


def _all_keys(obj: Any) -> list[str]:
    if isinstance(obj, dict):
        return [k for k in obj] + [x for v in obj.values() for x in _all_keys(v)]
    if isinstance(obj, list):
        return [x for v in obj for x in _all_keys(v)]
    return []


# ── 2) 프로세스 안: 주입 백엔드·어댑터 ───────────────────────────────────


def _call(server: Any, name: str, args: dict[str, Any]) -> Any:
    async def run() -> Any:
        async with Client(server) as c:
            return await c.call_tool(name, args)

    return asyncio.run(run())


def test_mcp_pseudonym_never_leaves_server(data_dir: Path) -> None:
    be = ms.build_default_backend(data_dir, data_dir / "index")
    rev = load_fixtures().reviews[0]
    with_pseudo = ReviewEvent.model_validate({**rev.model_dump(), "reviewer_pseudonym": "rvw_0123456789abcdef"})
    be.get_reviews = lambda wid: [with_pseudo]  # type: ignore[method-assign]
    res = _call(ms.create_server(be), "get_review_records", {"work_id": rev.work_id})
    assert not res.is_error, _text(res)
    assert "rvw_0123456789abcdef" not in _text(res)
    assert "rvw_0123456789abcdef" not in json.dumps(res.structured_content)
    assert res.structured_content["reviews"][0]["review_id"] == rev.review_id


def test_mcp_missing_sources_are_reported_not_hidden(tmp_path: Path) -> None:
    d = tmp_path / "data"
    _write_index(d / "index")  # processed/ 없음: 답변·결정·사후상태 파일이 없다
    server = ms.create_server(ms.build_default_backend(d, d / "index"))
    res = _call(server, "get_review_records", {"work_id": "fixture:seg-001"})
    assert not res.is_error, _text(res)
    notes = " ".join(res.structured_content["notes"])
    assert "author_responses.jsonl" in notes and "decisions.jsonl" in notes
    post = _call(server, "get_post_status", {"doi": FAKE_DOI})
    assert post.is_error and "사후상태" in _text(post)  # 파일이 없으면 no_record로 속이지 않는다
    empty = tmp_path / "empty"
    s2 = ms.create_server(ms.build_default_backend(empty, empty / "index"))
    res2 = _call(s2, "search_similar_works", {"query": "segmentation"})
    assert res2.is_error and "색인" in _text(res2)


def test_mcp_file_adapter_search(data_dir: Path, tmp_path: Path) -> None:
    fx = load_fixtures()
    idx = tmp_path / "idx"
    _write_jsonl(idx / "works.jsonl", fx.works)
    _write_jsonl(idx / "reviews.jsonl", fx.reviews)
    ad = ms.FileIndexAdapter(idx, "test reason")
    hits, status = ad.search("scaffold contrastive pretraining", 2)
    assert status == {"backend": "adapter_token_overlap", "degraded": True, "reason": "test reason"}
    assert hits[0].work_id == "fixture:gnn-002" and hits[0].score == 1.0 and hits[0].dense == 0.0
    assert len(hits) <= 2
    assert ad.search("zzzz qqqq", 5)[0] == []
    assert ad.get_work("nope") is None and len(ad.get_reviews("fixture:gnn-002")) == 2


def test_mcp_normalize_doi_rule() -> None:
    assert ms.normalize_doi(" https://doi.org/10.1000/ABC%3C1%3E ") == "10.1000/abc<1>"
    assert ms.normalize_doi("doi:10.1000/x") == "10.1000/x"
    assert ms.normalize_doi("http://dx.doi.org/10.1000/Y") == "10.1000/y"
    assert ms.normalize_doi("unavailable") is None and ms.normalize_doi("") is None
