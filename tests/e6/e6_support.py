"""E6 테스트 공용 도구: 외부 네트워크 차단기, 스크립트 로더, 가짜 파이프라인."""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "precompute_demo.py"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def load_script() -> ModuleType:
    """scripts/precompute_demo.py를 모듈로 읽는다(scripts/는 패키지가 아니다)."""
    name = "precompute_demo_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _host(address: Any) -> str:
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    return str(host)


@contextmanager
def block_external_network() -> Iterator[list[tuple[str, str]]]:
    """루프백이 아닌 곳으로의 연결·이름 조회를 막고 시도를 기록한다.

    루프백은 허용한다: Windows asyncio 이벤트 루프가 socketpair를 127.0.0.1 연결로 만든다.
    """
    attempts: list[tuple[str, str]] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def connect(self: socket.socket, address: Any) -> Any:
        if _host(address) in LOCAL_HOSTS:
            return real_connect(self, address)
        attempts.append(("connect", _host(address)))
        raise OSError("외부 네트워크 차단(테스트)")

    def connect_ex(self: socket.socket, address: Any) -> Any:
        if _host(address) in LOCAL_HOSTS:
            return real_connect_ex(self, address)
        attempts.append(("connect_ex", _host(address)))
        raise OSError("외부 네트워크 차단(테스트)")

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host is None or _host(host) in LOCAL_HOSTS:
            return real_getaddrinfo(host, *args, **kwargs)
        attempts.append(("getaddrinfo", _host(host)))
        raise socket.gaierror("외부 네트워크 차단(테스트)")

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    try:
        yield attempts
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = real_getaddrinfo  # type: ignore[assignment]


LIVE_WHEN = "2026-09-30T12:20:00Z"  # 가짜 라이브 결과 생성 시각(KST 21:20)


def fake_live_result(plan_rel: str, *, provider: str = "openai", model: str = "gpt-6.1-sol", when: str = LIVE_WHEN,
                     rule_cards: int = 0, session_id: str = "sess_live0001") -> dict[str, Any]:
    """E5-L1e2e 라이브 결과를 흉내 낸 가짜 PremortemResult JSON(실제 결과 파일은 저장소에 넣지 않는다).

    AI4S 계획서는 공용 fixture의 근거·카드(가짜 데이터)를 빌려 generator=astra·model=<model>로 붙인다.
    범위 밖(negative_recipe)은 카드 0장 + 사유. manifest에 llm_provider·llm_model을 적는다(파이프라인과 같은 키).
    """
    from neumann.models import PlanDocument
    from tests.fixtures.loader import FIXTURES_DIR

    text = (ROOT / plan_rel).read_text(encoding="utf-8")
    plan = PlanDocument.from_text(text, session_id=session_id)
    fx = json.loads((FIXTURES_DIR / "premortem_result.json").read_text(encoding="utf-8"))
    oos = Path(plan_rel).name == "negative_recipe.md"
    cards = [] if oos else [{**c, "generator": "astra", "model": model} for c in fx["risk_cards"]]
    for c in cards[:rule_cards]:
        c.update(generator="rule", model=None)
    impl = f"{provider}:{model}"
    stages = [{"name": "fitness", "status": "ok", "phase": "INPUT", "impl": impl}]
    stages += [] if oos else [{"name": "synthesize_cards", "status": "ok", "phase": "RISK", "impl": impl}]
    return {
        "session_id": session_id,
        "plan_id": plan.plan_id,
        "generated_at": when,
        "status": "ok",
        "plan": plan.model_dump(mode="json"),
        "similar_works": [] if oos else fx["similar_works"],
        "evidence": [] if oos else fx["evidence"],
        "risk_cards": cards,
        "stages": stages,
        "notices": [],
        "risk_synthesis": {"no_card_reason": "입력이 연구계획서가 아니다(가짜)"} if oos else {},
        "manifest": {"pipeline_version": "neumann-1", "llm_provider": provider, "llm_model": model, "total_s": 61.2},
    }


def write_live_results(folder: Path, plans: list[str], **kw: Any) -> Path:
    """E5-L1e2e 저장 모양(`<접두어>_live/<계획서>.result.json`)으로 가짜 라이브 결과를 쓴다."""
    folder.mkdir(parents=True, exist_ok=True)
    for rel in plans:
        data = fake_live_result(rel, **kw)
        (folder / f"{Path(rel).stem}.result.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def fake_pipeline_result(plan_text: str, session_id: str) -> dict[str, Any]:
    """가짜 run_premortem 결과: plan.md는 fixture 카드 2장(astra 1·rule 1), 다른 계획서는 카드 0장."""
    from neumann.models import PlanDocument
    from tests.fixtures.loader import FIXTURES_DIR

    plan = PlanDocument.from_text(plan_text, session_id=session_id)
    fixture = json.loads((FIXTURES_DIR / "premortem_result.json").read_text(encoding="utf-8"))
    if fixture["plan_id"] == plan.plan_id:
        fixture["session_id"] = session_id
        fixture["plan"]["session_id"] = session_id
        fixture["risk_cards"][0]["generator"] = "astra"
        fixture["risk_cards"][0]["model"] = "gpt-6-astra"
        fixture["risk_cards"][1]["generator"] = "rule"
        fixture["notices"] = []
        return fixture
    return {
        "session_id": session_id,
        "plan_id": plan.plan_id,
        "plan": plan.model_dump(mode="json"),
        "stages": [{"name": "search", "status": "skipped", "reason": "가짜: 색인 없음"}],
        "risk_synthesis": {"no_card_reason": "가짜 파이프라인: 카드 없음"},
    }
