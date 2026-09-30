"""E4-L2e 서버 모드용 실행기: 실제 API 앱(neumann.api.main) + 지연 mock provider + 계측 경로.

    NEUMANN_LLM_PROVIDER=mock python scripts/loadtest_multiuser_app.py --port 8145 --max-concurrent 12

- 앱은 main의 라우트 그대로다(`/premortem`, `/premortem/view`). 검색·임베딩·색인은 실제(data/index, bge-m3)다.
- LLM은 `DelayedMockProvider`(실제 OpenAI 안 부름, OpenAIProvider 호출은 막아 둠).
- 동시 상한: main의 `MAX_CONCURRENT`(현재 2 고정)와 E4-L2c 서빙 층의 `NEUMANN_MAX_CONCURRENT`를 둘 다 `--max-concurrent`로.
- 시험 전용 경로(이 실행기에서만 붙는다):
  `GET /_loadtest/stats`   이 프로세스의 자원 표본·임베딩 락 통계·요청별 기록(지문·단계 시간·임베딩 대기)
  `POST /_loadtest/reset`  {"scale": 지연 배율} 기록·표본을 비우고 배율을 바꾼다
- 8010·8020(사람이 쓰는 서버)에는 뜨지 않는다.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from loadtest_multiuser_lib import (  # noqa: E402
    CallStats,
    DelayedMockProvider,
    EmbedProbe,
    ProcSampler,
    block_openai,
    fingerprint,
    parse_delays,
    require_mock_env,
    stage_states,
    text_key,
)

FORBIDDEN_PORTS = {8010, 8020}


class Recorder:
    """요청별 기록. 파이프라인을 부른 스레드에서 임베딩 락 대기를 앞뒤 차이로 잰다."""

    def __init__(self, probe: EmbedProbe, delays: dict[str, tuple[float, float]], scale: float) -> None:
        self.probe = probe
        self.delays = delays
        self.scale = scale
        self.records: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.t0 = time.perf_counter()
        self.seed = 0
        self.active = 0
        self.max_active = 0

    def reset(self, scale: float | None) -> None:
        with self.lock:
            self.records = []
            self.t0 = time.perf_counter()
            self.max_active = self.active
            if scale is not None:
                self.scale = float(scale)

    def make_llm(self, settings: Any = None, provider: str | None = None) -> DelayedMockProvider:  # noqa: ARG002
        with self.lock:
            self.seed += 1
            seed = self.seed
        return DelayedMockProvider(self.delays, scale=self.scale, seed=seed, stats=CallStats())

    def wrap(self, run_premortem: Any) -> Any:
        def run(plan_text: str, **kwargs: Any) -> Any:
            llm = self.make_llm()
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                t_start = time.perf_counter() - self.t0
            e0 = self.probe.thread_totals()
            rec: dict[str, Any] = {"key": text_key(plan_text), "t_start": round(t_start, 3), "error": None}
            try:
                result = run_premortem(plan_text, llm=llm, **kwargs)
                d = result.model_dump(mode="json")
                rec.update(
                    status=d.get("status"),
                    fingerprint=fingerprint(d),
                    stage_states=stage_states(d),
                    timings_s=d.get("manifest", {}).get("timings_s", {}),
                    total_s=d.get("manifest", {}).get("total_s"),
                )
                return result
            except Exception as exc:  # noqa: BLE001 — 기록하고 다시 올린다(앱이 500으로 답한다)
                rec["error"] = type(exc).__name__
                raise
            finally:
                e1 = self.probe.thread_totals()
                rec["embed"] = {"calls": e1["n"] - e0["n"], "wait_s": round(e1["wait"] - e0["wait"], 4),
                                "hold_s": round(e1["hold"] - e0["hold"], 4)}
                rec["llm"] = llm.stats.totals()
                with self.lock:
                    self.active -= 1
                    rec["t_end"] = round(time.perf_counter() - self.t0, 3)
                    rec["run_s"] = round(rec["t_end"] - rec["t_start"], 3)
                    self.records.append(rec)

        return run


def build_app(max_concurrent: int, delays: dict[str, tuple[float, float]], scale: float) -> Any:
    require_mock_env()
    block_openai()
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ["NEUMANN_MAX_CONCURRENT"] = str(max_concurrent)  # E4-L2c 서빙 층이 붙어 있으면 이 값을 읽는다

    probe = EmbedProbe.install()
    sampler = ProcSampler().start()
    rec = Recorder(probe, delays, scale)

    import neumann.pipeline as pipeline_mod
    from neumann.api import main

    pipeline_mod.make_llm = rec.make_llm  # run_premortem(llm=None)이어도 지연 mock만 쓴다
    pipeline_mod.run_premortem = rec.wrap(pipeline_mod.run_premortem)
    main.MAX_CONCURRENT = max_concurrent
    main._sem = None  # noqa: SLF001 — 첫 요청 때 새 상한으로 만든다

    from fastapi import Body

    @main.app.get("/_loadtest/stats", include_in_schema=False)
    def _stats() -> dict[str, Any]:
        with rec.lock:
            records = list(rec.records)
            max_active = rec.max_active
        return {
            "sampler": sampler.snapshot(),
            "embed": probe.snapshot(),
            "records": records,
            "max_active_pipelines": max_active,
            "config": {"max_concurrent": max_concurrent, "scale": rec.scale, "delays": delays},
            "warmup": getattr(probe, "warmup", None),
            "pid": os.getpid(),
        }

    @main.app.post("/_loadtest/reset", include_in_schema=False)
    def _reset(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
        rec.reset(body.get("scale"))
        probe.reset()
        sampler.reset()
        return {"ok": True, "scale": rec.scale}

    return main.app


def main_cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E4-L2e 서버 모드 실행기(지연 mock + 계측)")
    ap.add_argument("--port", type=int, default=8145)
    ap.add_argument("--max-concurrent", type=int, default=12)
    ap.add_argument("--delay-scale", type=float, default=1.0)
    ap.add_argument("--delay", action="append", default=[], help="task=초 또는 task=최소:최대")
    args = ap.parse_args(argv)
    if args.port in FORBIDDEN_PORTS:
        raise SystemExit(f"{args.port}번은 쓰지 않는다(사람이 쓰는 서버)")
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    app = build_app(args.max_concurrent, parse_delays(args.delay), args.delay_scale)
    import uvicorn

    print(f"[loadtest-app] pid={os.getpid()} port={args.port} max_concurrent={args.max_concurrent}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
