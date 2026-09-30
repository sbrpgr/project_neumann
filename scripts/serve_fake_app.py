"""부하 시험·감시 시험용 앱: 실제 main.py 라우트 + 서빙 층 + **가짜 느린 파이프라인**(E4-L2c).

실제 분석(bge-m3·OpenAI)을 부르지 않는다. 결과는 공용 fixture(가짜 데이터)에 요청 계획서의 plan_id·줄을 붙인 것이다.
PM이 main.py에 붙일 모양(``_load_pipeline``이 ``serving.wrap_pipeline(fn)``을 돌려주고 main의 세마포어는 없앰)을
이 프로세스 안에서만 흉내 낸다.

    python -m uvicorn scripts.serve_fake_app:app --port 8122
    python scripts/serve.py --app scripts.serve_fake_app:app --port 8122

환경변수: NEUMANN_FAKE_RUN_S(가짜 분석 시간, 기본 2초), NEUMANN_FAKE_CRASH=1이면 ``POST /__crash``가 프로세스를 죽인다.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from neumann.api import main as api_main
from neumann.api import serving

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "premortem_result.json"


class _NoLimit:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> None:
        return None


def fake_result(plan_text: str) -> dict[str, Any]:
    """fixture 결과 + 요청 계획서의 plan_id·줄. 내용은 가짜([FAKE])다."""
    from neumann.models import PlanDocument

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sid = "sess_" + uuid.uuid4().hex[:12]
    doc = PlanDocument.from_text(plan_text, sid)
    data.update({
        "plan_id": doc.plan_id, "session_id": sid, "plan": doc.model_dump(mode="json"), "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notices": ["[FAKE] 가짜 느린 파이프라인(부하 시험용) 결과", *data.get("notices", [])],
    })
    return data


def make_slow_pipeline(run_s: float) -> Callable[..., dict[str, Any]]:
    def run_premortem(plan_text: str) -> dict[str, Any]:
        time.sleep(run_s)
        return fake_result(plan_text)

    return run_premortem


def integrate(srv: serving.Serving, fn: Callable[..., Any],
              setattr_: Callable[[Any, str, Any], None] = setattr) -> FastAPI:
    """main.py 라우트를 새 앱에 담고, PM 통합 모양으로 파이프라인을 감싸 서빙 층을 붙인다.

    테스트는 ``setattr_``에 ``monkeypatch.setattr``을 넘겨 main 모듈 패치를 되돌린다.
    """
    app = FastAPI(title="Neumann (fake pipeline)")
    app.router.routes.extend(api_main.app.router.routes)
    wrapped = srv.wrap_pipeline(fn)
    setattr_(api_main, "_load_pipeline", lambda: (wrapped, "connected", ""))
    setattr_(api_main, "_semaphore", lambda: _NoLimit())
    serving.install(app, srv)
    return app


def _build() -> FastAPI:
    srv = serving.Serving()
    app = integrate(srv, make_slow_pipeline(float(os.getenv("NEUMANN_FAKE_RUN_S", "2"))))
    if os.getenv("NEUMANN_FAKE_CRASH") == "1":
        @app.post("/__crash", include_in_schema=False)
        def crash() -> None:  # 감시 스크립트 시험용: 프로세스를 바로 죽인다
            os._exit(3)
    return app


_APP: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """``app``은 uvicorn이 가져갈 때 만든다(테스트가 이 모듈을 import 해도 main을 패치하지 않게)."""
    global _APP
    if name == "app":
        if _APP is None:
            _APP = _build()
        return _APP
    raise AttributeError(name)
