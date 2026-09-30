"""/health가 서버 코드 커밋과 기동 시각을 알려 준다(어느 main으로 떴는지 확인용)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from neumann.api.main import app


def test_health_has_commit_and_start_time():
    body = TestClient(app).get("/health").json()
    assert re.fullmatch(r"[0-9a-f]{4,40}|unknown", body["commit"])
    assert re.match(r"\d{4}-\d{2}-\d{2}T", body["started_at"])
