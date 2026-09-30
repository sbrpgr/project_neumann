"""Bounded, synthetic Windows filename cases; no services or network."""
from __future__ import annotations

import asyncio
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neumann.api import main, serving


def font_app():
    fonts = next(route.app for route in main.app.routes if getattr(route, "name", None) == "fonts")
    app = FastAPI()
    app.mount("/fonts", fonts, name="fonts")
    serving.install(app, serving.Serving(serving.ServingConfig()))
    return app, fonts


@pytest.mark.parametrize("name", ["a<b", "a|b", "a\x01b", "a" * 256], ids=["angle", "pipe", "control-01", "segment-256"])
def test_invalid_windows_font_filename_is_404_before_stat(monkeypatch, name):
    app, fonts = font_app()
    calls = []
    original = fonts.lookup_path

    def lookup(path):
        calls.append(1)
        return original(path)

    monkeypatch.setattr(fonts, "lookup_path", lookup)
    response = TestClient(app, raise_server_exceptions=False).get("/fonts/" + quote(name, safe=""))
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert calls == []
    for key, value in serving.SECURITY_HEADERS:
        assert response.headers[key.decode()] == value.decode()


def test_bundled_font_and_missing_font_behavior():
    app, _ = font_app()
    fonts_root = main.WEBUI_DIR / "fonts"
    sample = next(fonts_root.rglob("*.woff2"))
    path = "/fonts/" + sample.relative_to(fonts_root).as_posix()
    client = TestClient(app)
    response = client.get(path)
    assert response.status_code == 200
    assert response.content == sample.read_bytes()
    assert client.head(path).status_code == 200
    assert client.get("/fonts/missing.woff2").status_code == 404
    assert client.get("/fonts/%2e%2e/../AGENTS.md").status_code == 404


@pytest.mark.parametrize("name", ["NUL.woff2", "CON", "lpt1.ttf", "a:b", "a*", "a?", 'a"b', "a ", "a.", "a\\b", "\U0001f600" * 128],
                         ids=["nul", "con", "lpt", "ads", "star", "question", "quote", "space", "dot", "backslash", "utf16-256"])
def test_other_unsafe_font_names_are_early_404(monkeypatch, name):
    app, fonts = font_app()

    def no_stat(path):
        pytest.fail("unsafe font filename reached filesystem")

    monkeypatch.setattr(fonts, "lookup_path", no_stat)
    response = TestClient(app).get("/fonts/" + quote(name, safe=""))
    assert response.status_code == 404


def test_font_filename_boundary_and_error_fallback(monkeypatch):
    assert main._safe_font_path("/fonts/Pretendard/PretendardVariable.woff2")
    assert main._safe_font_path("/fonts/" + "a" * 255)
    assert main._safe_font_path("/fonts/" + "\U0001f600" * 127 + "a")
    assert not main._safe_font_path("/fonts/" + "a" * 256)
    app, fonts = font_app()

    def filesystem_error(path):
        raise OSError("synthetic-private-filesystem-detail")

    monkeypatch.setattr(fonts, "lookup_path", filesystem_error)
    response = TestClient(app).get("/fonts/valid-name.woff2")
    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}
    assert "synthetic-private" not in response.text


def test_raw_asgi_font_traversal_is_404_without_filesystem(monkeypatch):
    app, fonts = font_app()

    def no_stat(path):
        pytest.fail("font traversal reached filesystem")

    monkeypatch.setattr(fonts, "lookup_path", no_stat)

    async def go(path):
        messages = []
        scope = {"type": "http", "http_version": "1.1", "method": "GET", "scheme": "http", "path": path,
                 "raw_path": path.encode("ascii"), "query_string": b"", "headers": [],
                 "client": ("192.0.2.1", 1234), "server": ("synthetic", 80)}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await app(scope, receive, send)
        assert next(m for m in messages if m["type"] == "http.response.start")["status"] == 404

    for path in ("/fonts/../AGENTS.md", "/fonts/Pretendard/../../AGENTS.md"):
        asyncio.run(go(path))


def test_font_guard_mutation_is_detected(monkeypatch):
    from fastapi.staticfiles import StaticFiles

    monkeypatch.setattr(main, "_safe_font_path", lambda path: True)
    monkeypatch.setattr(main._FontFiles, "get_response", StaticFiles.get_response)
    with pytest.raises(AssertionError):
        test_invalid_windows_font_filename_is_404_before_stat(monkeypatch, "a<b")
