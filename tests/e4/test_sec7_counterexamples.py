"""SEC-7 기준 9의 독립 반례: 합성 ASGI 경계, 폴링 경로, 이전 결함 변이."""

from __future__ import annotations

import asyncio
from urllib.parse import unquote_to_bytes

import pytest
from fastapi import FastAPI, Response

from neumann.api import jobs, serving


def make_app(*, get_rate=2, poll_rate=3, catch_all=False):
    app = FastAPI()
    srv = serving.Serving(serving.ServingConfig(get_rate_per_min=get_rate, max_request_line=8192))
    serving.install(app, srv)
    store = jobs.install(app, load_pipeline=lambda: (None, "unavailable", "synthetic"),
                         config=jobs.JobsConfig(poll_per_min=poll_rate))
    assert store is not None

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    if catch_all:
        @app.get("/{rest:path}")
        async def accept(rest: str):
            return Response(status_code=204)
    return app, srv, store


async def request(app, raw_path, query=b"", *, method="GET", peer="192.0.2.1"):
    messages = []
    scope = {"type": "http", "http_version": "1.1", "method": method, "scheme": "http",
             "path": unquote_to_bytes(raw_path).decode("utf-8"), "raw_path": raw_path,
             "query_string": query, "headers": [], "client": (peer, 1234), "server": ("synthetic", 80)}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert all(headers.get(k) == v for k, v in serving.SECURITY_HEADERS)
    return start["status"]


async def assert_no_query_boundary(app):
    assert await request(app, b"/" + b"x" * 8191) == 204
    assert await request(app, b"/" + b"x" * 8192) == 414


@pytest.mark.parametrize("target_size,expected", [(8191, 204), (8192, 204), (8193, 414)])
@pytest.mark.parametrize("query", [b"", b"q"])
def test_request_target_exact_byte_boundary(target_size, expected, query):
    app, _, _ = make_app(get_rate=0, catch_all=True)
    raw_path = b"/" + b"x" * (target_size - 1 - (1 + len(query) if query else 0))
    assert len(raw_path) + (1 + len(query) if query else 0) == target_size
    assert asyncio.run(request(app, raw_path, query)) == expected


@pytest.mark.parametrize("target_size,expected", [(8192, 204), (8193, 414)])
def test_target_cap_counts_percent_encoded_wire_bytes(target_size, expected):
    app, _, _ = make_app(get_rate=0, catch_all=True)
    raw_path = b"/" + b"%78" * 1000 + b"x" * (target_size - 3001)
    assert len(raw_path) == target_size
    assert len(unquote_to_bytes(raw_path)) < 8192
    assert asyncio.run(request(app, raw_path)) == expected


async def assert_nonpolling_get_rate(app, path):
    codes = [await request(app, path) for _ in range(3)]
    assert codes[:2] in ([404, 404], [307, 307])
    assert codes[2] == 429
    assert await request(app, path, peer="192.0.2.2") in (404, 307)


@pytest.mark.parametrize("path", [b"/premortem/jobs/missing/extra", b"/premortem/jobs/",
                                   b"/premortem/jobs//missing", b"/premortem/jobs/missing/",
                                   b"/premortem/jobs/missing%2Fextra"])
def test_nonpolling_job_prefix_routes_use_get_rate_limit(path):
    app, _, store = make_app()
    asyncio.run(assert_nonpolling_get_rate(app, path))
    assert not store.poll_limiter._hits  # 일반 404/redirect는 폴링 핸들러에 들어가지 않는다.


@pytest.mark.parametrize("job_id", [b"missing", b"Synthetic_" + b"a" * 22])
def test_exact_polling_route_keeps_its_own_rate_limit(job_id):
    app, srv, store = make_app(get_rate=1, poll_rate=3)

    async def go():
        path = b"/premortem/jobs/" + job_id
        assert [await request(app, path) for _ in range(4)] == [404, 404, 404, 429]
        assert not srv.get_limiter._hits
        assert store.counters["poll_429"] == 1
        assert await request(app, b"/health") == 200
        assert await request(app, b"/health") == 429
    asyncio.run(go())


def test_non_get_single_segment_job_route_has_no_poll_exemption():
    app, _, _ = make_app()

    async def go():
        assert [await request(app, b"/premortem/jobs/missing", method="HEAD") for _ in range(3)] == [405, 405, 429]
    asyncio.run(go())


def test_mutation_phantom_query_separator_breaks_boundary_assertion(monkeypatch):
    original = serving.ServingMiddleware._precheck

    def phantom_separator(self, scope, path):
        if not scope.get("query_string"):
            scope = {**scope, "raw_path": scope["raw_path"] + b"?"}
        return original(self, scope, path)

    monkeypatch.setattr(serving.ServingMiddleware, "_precheck", phantom_separator)
    app, _, _ = make_app(get_rate=0, catch_all=True)
    with pytest.raises(AssertionError):
        asyncio.run(assert_no_query_boundary(app))


def test_mutation_prefix_exemption_breaks_nonpolling_rate_assertion(monkeypatch):
    original = serving.ServingMiddleware._precheck

    def prefix_exemption(self, scope, path):
        if scope.get("method") == "GET" and path.startswith(serving.JOB_POLL_PREFIX):
            return None
        return original(self, scope, path)

    monkeypatch.setattr(serving.ServingMiddleware, "_precheck", prefix_exemption)
    app, _, _ = make_app()
    with pytest.raises(AssertionError):
        asyncio.run(assert_nonpolling_get_rate(app, b"/premortem/jobs/missing/extra"))
