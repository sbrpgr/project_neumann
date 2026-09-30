"""E4-L2e 다중 사용자 부하 시험: 동시 분석 몇 건까지 안정적인가(공개 서버 NEUMANN_MAX_CONCURRENT 권장값).

    NEUMANN_LLM_PROVIDER=mock python scripts/loadtest_multiuser.py all --out docs/reports/E4-L2e_results.json
    NEUMANN_LLM_PROVIDER=mock python scripts/loadtest_multiuser.py direct --n 1,2,4
    NEUMANN_LLM_PROVIDER=mock python scripts/loadtest_multiuser.py server --n 1,2,4 --port 8145
    NEUMANN_LLM_PROVIDER=mock python scripts/loadtest_multiuser.py encode --n 1,4,12

모드
- `direct`: 이 프로세스에서 스레드 N개가 `run_premortem`을 동시에 부른다(서버와 같이 backend·settings는 기본값).
- `server`: `scripts/loadtest_multiuser_app.py`를 8145번에 띄우고(끝나면 종료) N명이 `POST /premortem/view`를 동시에 보낸다.
- `encode`: 같은 bge-m3 모델을 스레드들이 동시에 encode — 제품 경로(락)와 락 없이(모델 직접) 오류·결과 불일치·처리량.
- `all`: encode → direct → server 순서로 다 돌리고 JSON 하나에 모은다.

공통
- LLM은 `DelayedMockProvider`(과제별 지연, 기본 합계 약 60초). 실제 OpenAI는 부르지 않는다: `NEUMANN_LLM_PROVIDER=mock`을
  명시해야 시작하고, OpenAIProvider 호출은 막아 두며, 서버 자식 프로세스 환경에서 OPENAI_API_KEY를 뺀다.
- 검색·임베딩·색인은 실제(`NEUMANN_DATA_DIR`/index, bge-m3 GPU).
- 사용자 k의 계획서 = 기반 계획서(데모 3·예시 2·템플릿 골격 5) k mod 10 + 변형 줄(라운드·사용자 번호) → 요청마다 본문이 다르다.
- 지문 대조: 모든 본문을 먼저 지연 0으로 순차 실행한 결과(기준)와 동시 실행 결과를 비교한다(모두 결정적이라 같아야 한다).
  이 순차 실행이 색인·발췌 캐시 예열도 겸한다.
- 측정: 건별 총 시간·단계별 시간(검색 단계는 임베딩 락 대기 포함, 락 대기는 따로), 처리량, nvidia-smi GPU 메모리 최대,
  프로세스 메모리 최대, CPU(코어 수 환산), GIL 지연 탐침, 오류·예외, 지문 불일치, 검색 상태 섞임(전역 last_search_status).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from loadtest_multiuser_lib import (  # noqa: E402
    ROOT,
    CallStats,
    DelayedMockProvider,
    EmbedProbe,
    GpuPoller,
    ProcSampler,
    block_openai,
    fingerprint,
    nvidia_smi,
    parse_delays,
    plan_bases,
    require_mock_env,
    round_texts,
    stage_states,
    stats,
    text_key,
)

DEFAULT_NS = (1, 2, 4, 6, 8, 12)
FORBIDDEN_PORTS = {8010, 8020}
STAGES = ("fitness", "query_axes", "search", "extract_issues", "synthesize_cards", "verify_evidence",
          "expected_review", "checklist", "semantic_validate")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def all_texts(ns: tuple[int, ...]) -> dict[int, list[tuple[str, str]]]:
    bases = plan_bases()
    return {n: round_texts(bases, n, f"{n}") for n in ns}


# ── 직접 호출 ─────────────────────────────────────────────────────────────


def _run_one(text: str, delays: dict[str, tuple[float, float]], scale: float, seed: int, probe: EmbedProbe,
             t_round: float, backend: Any = None) -> dict[str, Any]:
    from neumann.pipeline import run_premortem

    llm = DelayedMockProvider(delays, scale=scale, seed=seed, stats=CallStats())
    e0 = probe.thread_totals()
    t0 = time.perf_counter()
    rec: dict[str, Any] = {"key": text_key(text), "t_start": round(t0 - t_round, 3), "error": None}
    try:
        result = run_premortem(text, llm=llm, backend=backend)  # backend None = 서버와 같은 기본(실색인)
        d = result.model_dump(mode="json")
        rec.update(status=d.get("status"), fingerprint=fingerprint(d), stage_states=stage_states(d),
                   timings_s=d.get("manifest", {}).get("timings_s", {}))
    except Exception as exc:  # noqa: BLE001
        rec["error"] = type(exc).__name__
    t1 = time.perf_counter()
    e1 = probe.thread_totals()
    rec.update(t_end=round(t1 - t_round, 3), run_s=round(t1 - t0, 3), total_s=round(t1 - t0, 3),
               embed={"calls": e1["n"] - e0["n"], "wait_s": round(e1["wait"] - e0["wait"], 4),
                      "hold_s": round(e1["hold"] - e0["hold"], 4)},
               llm=llm.stats.totals())
    return rec


def reference_pass(texts: list[str], delays: dict[str, tuple[float, float]], probe: EmbedProbe,
                   backend: Any = None) -> dict[str, dict[str, Any]]:
    """모든 본문을 지연 0으로 순차 실행 → 본문 키별 기준 기록(지문·계산 시간). 예열도 겸한다."""
    ref: dict[str, dict[str, Any]] = {}
    t = time.perf_counter()
    for i, text in enumerate(texts):
        rec = _run_one(text, delays, 0.0, i, probe, t, backend)
        ref[rec["key"]] = rec
    return ref


def run_round_direct(texts: list[tuple[str, str]], delays: dict[str, tuple[float, float]], scale: float,
                     probe: EmbedProbe, sampler: ProcSampler, backend: Any = None) -> dict[str, Any]:
    n = len(texts)
    records: list[dict[str, Any] | None] = [None] * n
    barrier = threading.Barrier(n + 1)
    t_round = [0.0]

    def worker(i: int) -> None:
        barrier.wait()
        rec = _run_one(texts[i][1], delays, scale, 1000 * n + i, probe, t_round[0], backend)
        rec["base"] = texts[i][0]
        records[i] = rec

    sampler.reset()
    probe.reset()
    threads = [threading.Thread(target=worker, args=(i,), name=f"user-{i}") for i in range(n)]
    for t in threads:
        t.start()
    with GpuPoller() as gpu:
        t_round[0] = time.perf_counter()
        barrier.wait()
        for t in threads:
            t.join()
        makespan = time.perf_counter() - t_round[0]
    return {"n": n, "makespan_s": round(makespan, 3), "records": records, "sampler": sampler.snapshot(),
            "embed": probe.snapshot(), "gpu": gpu.summary()}


# ── 서버 ──────────────────────────────────────────────────────────────────


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


class ServerProc:
    """loadtest_multiuser_app.py 자식 프로세스(끝나면 반드시 종료)."""

    def __init__(self, port: int, max_concurrent: int, scale: float, delay_args: list[str], log_path: Path) -> None:
        if port in FORBIDDEN_PORTS:
            raise SystemExit(f"{port}번은 쓰지 않는다")
        if port_open(port):
            raise SystemExit(f"{port}번이 이미 쓰이고 있다")
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        env.update(NEUMANN_LLM_PROVIDER="mock", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        cmd = [sys.executable, str(ROOT / "scripts" / "loadtest_multiuser_app.py"), "--port", str(port),
               "--max-concurrent", str(max_concurrent), "--delay-scale", str(scale)]
        for d in delay_args:
            cmd += ["--delay", d]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
        self.proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self.port = port
        self.base = f"http://127.0.0.1:{port}"

    def wait_ready(self, timeout: float = 240.0) -> float:
        import httpx

        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError(f"서버가 먼저 끝났다(코드 {self.proc.returncode})")
            try:
                if httpx.get(self.base + "/health", timeout=2).status_code == 200:
                    return time.perf_counter() - t0
            except httpx.HTTPError:
                pass
            time.sleep(1.0)
        raise TimeoutError("서버 준비 시간 초과")

    def stop(self) -> bool:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=30)
        self.log.close()
        time.sleep(1.0)
        return not port_open(self.port)


def run_round_server(srv: ServerProc, texts: list[tuple[str, str]], scale: float, endpoint: str) -> dict[str, Any]:
    import httpx

    n = len(texts)
    httpx.post(srv.base + "/_loadtest/reset", json={"scale": scale}, timeout=30).raise_for_status()
    records: list[dict[str, Any] | None] = [None] * n
    barrier = threading.Barrier(n + 1)
    t_round = [0.0]

    def worker(i: int) -> None:
        name, text = texts[i]
        with httpx.Client(timeout=900) as client:
            barrier.wait()
            t0 = time.perf_counter()
            rec: dict[str, Any] = {"key": text_key(text), "base": name, "error": None}
            try:
                r = client.post(srv.base + endpoint, json={"plan_text": text})
                rec.update(http=r.status_code, bytes=len(r.content))
                if r.status_code != 200:
                    rec["error"] = f"HTTP {r.status_code}"
            except httpx.HTTPError as exc:
                rec["error"] = type(exc).__name__
            t1 = time.perf_counter()
            rec.update(c_start=round(t0 - t_round[0], 3), c_end=round(t1 - t_round[0], 3), client_s=round(t1 - t0, 3))
            records[i] = rec

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    with GpuPoller() as gpu:
        t_round[0] = time.perf_counter()
        barrier.wait()
        for t in threads:
            t.join()
        makespan = time.perf_counter() - t_round[0]
    st = httpx.get(srv.base + "/_loadtest/stats", timeout=60).json()
    by_key = {r["key"]: r for r in st["records"]}
    for rec in records:
        assert rec is not None
        srec = by_key.get(rec["key"])
        if srec:
            for k in ("status", "fingerprint", "stage_states", "timings_s", "embed", "llm", "run_s"):
                rec[k] = srec.get(k)
            if srec.get("error") and not rec["error"]:
                rec["error"] = srec["error"]
            rec["total_s"] = rec["client_s"]
            rec["queue_s"] = round(max(0.0, rec["client_s"] - (srec.get("run_s") or 0.0)), 3)
        else:
            rec["total_s"] = rec["client_s"]
            rec["error"] = rec["error"] or "서버 기록 없음"
    return {"n": n, "makespan_s": round(makespan, 3), "records": records, "sampler": st["sampler"],
            "embed": st["embed"], "gpu": gpu.summary(), "max_active_pipelines": st["max_active_pipelines"]}


# ── 요약 ──────────────────────────────────────────────────────────────────


def summarize_round(rnd: dict[str, Any], ref: dict[str, dict[str, Any]], gpu_base: float | None) -> dict[str, Any]:
    recs = [r for r in rnd["records"] if r]
    errors = [r for r in recs if r.get("error")]
    stage_err = sum((r.get("stage_states") or {}).get("error", 0) for r in recs)
    ref_degraded = {k: (v.get("stage_states") or {}).get("degraded", 0) for k, v in ref.items()}
    new_degraded = sum(max(0, (r.get("stage_states") or {}).get("degraded", 0) - ref_degraded.get(r["key"], 0)) for r in recs)
    mism = [r["key"] for r in recs if r.get("fingerprint") and r["key"] in ref
            and r["fingerprint"]["digest"] != ref[r["key"]]["fingerprint"]["digest"]]
    mixup = sum(1 for r in recs if (r.get("fingerprint") or {}).get("status_mixup"))
    no_ref = sum(1 for r in recs if r["key"] not in ref)
    stage_mean = {s: stats([(r.get("timings_s") or {}).get(s, 0.0) for r in recs if r.get("timings_s")]) for s in STAGES}
    llm_calls = [r["llm"]["calls"] for r in recs if r.get("llm")]
    llm_chars = [r["llm"]["chars"] for r in recs if r.get("llm")]
    gpu = rnd.get("gpu") or {}
    out = {
        "n": rnd["n"],
        "ok": len(recs) - len(errors),
        "errors": len(errors),
        "error_kinds": sorted({str(r["error"]) for r in errors}),
        "stage_errors": stage_err,
        "new_degraded_stages": new_degraded,
        "fingerprint_mismatch": len(mism),
        "no_reference": no_ref,
        "search_status_mixup": mixup,
        "total_s": stats(r["total_s"] for r in recs),
        "run_s": stats(r.get("run_s") or 0.0 for r in recs),
        "queue_s": stats(r.get("queue_s", 0.0) for r in recs),
        "makespan_s": rnd["makespan_s"],
        "throughput_per_min": round(60.0 * len(recs) / rnd["makespan_s"], 2) if rnd["makespan_s"] else None,
        "stage_s": stage_mean,
        "embed_wait_s": stats((r.get("embed") or {}).get("wait_s", 0.0) for r in recs),
        "embed_round": rnd.get("embed"),
        "llm_calls_per_analysis": stats(llm_calls),
        "llm_input_chars_per_analysis": stats(llm_chars),
        "gpu_mem_max_mb": gpu.get("mem_max_mb"),
        "gpu_mem_delta_mb": round(gpu["mem_max_mb"] - gpu_base, 1) if gpu.get("mem_max_mb") and gpu_base is not None else None,
        "gpu_util_max_pct": gpu.get("util_max_pct"),
        "proc": rnd.get("sampler"),
    }
    if "max_active_pipelines" in rnd:
        out["max_active_pipelines"] = rnd["max_active_pipelines"]
    return out


def table(rows: list[dict[str, Any]], mode: str) -> str:
    head = ("| N | 성공 | 오류·예외 | 지문 불일치 | 검색상태 섞임 | 건별 총 시간 p50 / 최대(초) | 전체(초) | 처리량(건/분) "
            "| 검색 단계 최대(초) | 임베딩 락 대기 최대(초) | GPU 최대 MiB(Δ) | RAM 최대 MB(작업 집합/전용) | CPU 코어 평균/최대 "
            "| GIL 지연 p99/최대(ms) | 스레드 최대 |")
    lines = [head, "|" + "|".join(["---"] * (head.count("|") - 1)) + "|"]
    for r in rows:
        p = r.get("proc") or {}
        g = p.get("gil_probe_ms") or {}
        err = f"{r['errors']}+단계 {r['stage_errors']}" + (f" ({', '.join(r['error_kinds'])})" if r["error_kinds"] else "")
        gpu = "-" if r["gpu_mem_max_mb"] is None else f"{r['gpu_mem_max_mb']:.0f}"
        if r["gpu_mem_delta_mb"] is not None:
            gpu += f" ({r['gpu_mem_delta_mb']:+.0f})"
        lines.append(
            f"| {r['n']} | {r['ok']}/{r['n']} | {err} | {r['fingerprint_mismatch']} | {r['search_status_mixup']} "
            f"| {r['total_s'].get('p50')} / {r['total_s'].get('max')} | {r['makespan_s']} | {r['throughput_per_min']} "
            f"| {r['stage_s']['search'].get('max')} | {r['embed_wait_s'].get('max')} | {gpu} "
            f"| {p.get('rss_max_mb')}/{p.get('private_max_mb', '-')} "
            f"| {p.get('cores_avg')}/{p.get('cores_max')} | {g.get('p99')}/{g.get('max')} | {p.get('threads_max')} |"
        )
    return f"### {mode}\n\n" + "\n".join(lines)


def stage_table(rows: list[dict[str, Any]], mode: str) -> str:
    head = "| N | " + " | ".join(STAGES) + " |"
    lines = [f"### {mode} 단계별 평균(최대) 초", "", head, "|" + "|".join(["---"] * (len(STAGES) + 1)) + "|"]
    for r in rows:
        cells = [f"{r['stage_s'][s].get('mean')} ({r['stage_s'][s].get('max')})" for s in STAGES]
        lines.append(f"| {r['n']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ── 임베딩 동시 encode ────────────────────────────────────────────────────


def encode_test(probe: EmbedProbe, ns: tuple[int, ...], repeats: int) -> dict[str, Any]:
    """제품 경로(락) vs 락 없이 모델 직접: 스레드 N개가 서로 다른 질의 묶음을 repeats번씩 encode."""
    import numpy as np

    from neumann.analyze import rules
    from neumann.models import PlanDocument

    emb = probe.embedder
    if emb is None or not hasattr(emb, "_model"):
        return {"skipped": "bge-m3 임베더 없음"}
    texts = round_texts(plan_bases(), 12, "임베딩")
    qsets = [rules.fallback_queries(PlanDocument.from_text(t, "enc")) for _, t in texts]

    def raw(qs: list[str]) -> Any:
        return np.asarray(emb._model.encode(qs, batch_size=emb.batch_size, normalize_embeddings=True,  # noqa: SLF001
                                            convert_to_numpy=True, show_progress_bar=False), dtype=np.float32)

    ref = [emb.encode(q) for q in qsets]
    sanity = float(np.max(np.abs(ref[0][:1] - ref[1][:1])))  # 서로 다른 질의는 달라야 한다(비교기가 살아 있음)
    out: dict[str, Any] = {"n_query_sets": len(qsets), "queries_per_set": [len(q) for q in qsets],
                           "sanity_diff_between_different_queries": round(sanity, 4), "runs": []}
    for mode, fn in (("locked(product)", emb.encode), ("unlocked(raw model)", raw)):
        for n in ns:
            errs: list[str] = []
            diffs: list[float] = []
            exact = [0]
            lock = threading.Lock()
            barrier = threading.Barrier(n)

            def worker(i: int) -> None:
                barrier.wait()
                for r in range(repeats):
                    j = (i + r) % len(qsets)
                    try:
                        v = fn(qsets[j])
                    except Exception as exc:  # noqa: BLE001
                        with lock:
                            errs.append(type(exc).__name__)
                        continue
                    d = float(np.max(np.abs(v - ref[j]))) if v.shape == ref[j].shape else float("inf")
                    with lock:
                        diffs.append(d)
                        exact[0] += int(d == 0.0)

            t0 = time.perf_counter()
            ths = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
            dt = time.perf_counter() - t0
            out["runs"].append({"mode": mode, "n": n, "encodes": n * repeats, "errors": len(errs),
                                "error_kinds": sorted(set(errs)), "max_abs_diff": round(max(diffs), 6) if diffs else None,
                                "exact_equal": exact[0], "compared": len(diffs), "elapsed_s": round(dt, 3),
                                "encodes_per_s": round(n * repeats / dt, 1)})
            log(f"encode {mode} N={n}: {out['runs'][-1]}")
    return out


def encode_table(enc: dict[str, Any]) -> str:
    lines = ["### bge-m3 동시 encode(같은 모델 공유)", "",
             f"질의 묶음 {enc.get('n_query_sets')}개(묶음당 질의 {enc.get('queries_per_set')}), "
             f"서로 다른 질의 사이 최대 차이 {enc.get('sanity_diff_between_different_queries')}(비교기 정상 확인)", "",
             "| 방식 | N | encode 수 | 오류 | 순차 기준과 최대 차이 | 완전히 같음 | encode/초 |", "|---|---|---|---|---|---|---|"]
    for r in enc.get("runs", []):
        lines.append(f"| {r['mode']} | {r['n']} | {r['encodes']} | {r['errors']} | {r['max_abs_diff']} "
                     f"| {r['exact_equal']}/{r['compared']} | {r['encodes_per_s']} |")
    return "\n".join(lines)


def print_report(sources: list[Path]) -> int:
    """결과 JSON에서 표를 다시 그린다(보고서용)."""
    nl = "\n"
    for src in sources:
        res = json.loads(src.read_text(encoding="utf-8"))
        print(f"## {src.name} (N={res.get('ns')}, 지연 배율 {res.get('delay_scale')})" + nl)
        if "server" in res:
            label = f"서버({res['server'].get('port')}, {res['server'].get('endpoint')})"
            print(table(res["server"]["rounds"], label) + nl * 2 + stage_table(res["server"]["rounds"], label) + nl)
        if "direct" in res:
            label = "직접 호출(스레드)"
            print(table(res["direct"]["rounds"], label) + nl * 2 + stage_table(res["direct"]["rounds"], label) + nl)
        if "compute_only" in res:
            print(table(res["compute_only"]["rounds"], "직접 호출, 지연 0(계산만)") + nl)
        if "encode" in res:
            print(encode_table(res["encode"]) + nl)
    return 0


# ── 실행 ──────────────────────────────────────────────────────────────────


def parse_ns(s: str) -> tuple[int, ...]:
    ns = tuple(int(x) for x in s.split(",") if x.strip())
    if not ns or min(ns) < 1:
        raise argparse.ArgumentTypeError("N은 1 이상 정수 목록(예 1,2,4)")
    return ns


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(description="E4-L2e 다중 사용자 부하 시험(mock LLM 지연 + 실제 검색·임베딩)")
    ap.add_argument("mode", choices=["direct", "server", "encode", "all", "report"])
    ap.add_argument("--from", dest="sources", type=Path, action="append", default=[],
                    help="report: 결과 JSON(여러 번)에서 표만 다시 그린다")
    ap.add_argument("--n", type=parse_ns, default=DEFAULT_NS)
    ap.add_argument("--delay-scale", type=float, default=1.0, help="모든 mock 지연에 곱하는 배율(0이면 계산만)")
    ap.add_argument("--delay", action="append", default=[], help="task=초 또는 task=최소:최대(기본값 덮어쓰기)")
    ap.add_argument("--compute-only", action="store_true", help="direct에서 같은 본문으로 지연 0 라운드도 돌린다")
    ap.add_argument("--port", type=int, default=8145)
    ap.add_argument("--endpoint", default="/premortem/view")
    ap.add_argument("--encode-n", type=parse_ns, default=(1, 4, 12))
    ap.add_argument("--encode-repeats", type=int, default=20)
    ap.add_argument("--server-log", type=Path, default=None, help="서버 표준 출력 파일(기본: 결과 JSON 옆 또는 임시 폴더)")
    ap.add_argument("--out", type=Path, default=None, help="결과 JSON 경로")
    args = ap.parse_args(argv)
    if args.mode == "report":
        return print_report(args.sources)

    require_mock_env()
    block_openai()
    os.environ.pop("OPENAI_API_KEY", None)  # 이 프로세스에서는 키가 필요 없다
    delays = parse_delays(args.delay)
    ns = tuple(args.n)
    texts = all_texts(ns)
    uniq = list(dict.fromkeys(t for n in ns for _, t in texts[n]))
    result: dict[str, Any] = {
        "task": "E4-L2e", "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "ns": list(ns), "delays": delays,
        "delay_scale": args.delay_scale, "llm": "DelayedMockProvider(mock, 실제 OpenAI 호출 0)",
        "bases": [b for b, _ in plan_bases()], "n_texts": len(uniq), "gpu_before": nvidia_smi(),
    }
    log(f"시작: 모드 {args.mode}, N={ns}, 본문 {len(uniq)}개, GPU {result['gpu_before']}")

    sref: dict[str, dict[str, Any]] = {}
    if args.mode in ("server", "all"):
        # 서버를 먼저 돈다: 이 프로세스가 아직 CUDA를 안 올려서 nvidia-smi 값이 서버 몫만이다
        slog = args.server_log or ((args.out.parent if args.out else Path(os.environ.get("TEMP", "."))) / "E4-L2e_server.log")
        srv = ServerProc(args.port, max(ns), args.delay_scale, args.delay, slog)
        try:
            ready = srv.wait_ready()
            import httpx

            gpu_srv = nvidia_smi()
            log(f"서버 준비 {ready:.1f}s (포트 {args.port}), GPU {gpu_srv}")
            # 기준·예열: 지연 0으로 모든 본문을 순차 요청(서버 쪽 지문)
            httpx.post(srv.base + "/_loadtest/reset", json={"scale": 0.0}, timeout=30).raise_for_status()
            t0 = time.perf_counter()
            for t in uniq:
                httpx.post(srv.base + args.endpoint, json={"plan_text": t}, timeout=600).raise_for_status()
            st = httpx.get(srv.base + "/_loadtest/stats", timeout=60).json()
            sref = {r["key"]: r for r in st["records"]}
            result["server_reference"] = {"n": len(sref), "elapsed_s": round(time.perf_counter() - t0, 2),
                                          "compute_s": stats(r.get("run_s") or 0.0 for r in sref.values()),
                                          "errors": sum(1 for r in sref.values() if r.get("error")),
                                          "warmup": st.get("warmup")}
            log(f"서버 기준(지연 0 순차) {len(sref)}건 {result['server_reference']['elapsed_s']}s")
            gpu_base = (nvidia_smi() or {}).get("mem_used_mb")
            rows, raw = [], []
            for n in ns:
                log(f"server N={n} 시작")
                rnd = run_round_server(srv, texts[n], args.delay_scale, args.endpoint)
                row = summarize_round(rnd, sref, gpu_base)
                rows.append(row)
                raw.append(rnd["records"])
                log(f"server N={n}: 성공 {row['ok']}/{n} 총시간 {row['total_s']} 대기 {row['queue_s']} 처리량 "
                    f"{row['throughput_per_min']}/분 GPU {row['gpu_mem_max_mb']} RAM {row['proc']['rss_max_mb']}MB "
                    f"지문불일치 {row['fingerprint_mismatch']}")
            result["server"] = {"port": args.port, "endpoint": args.endpoint, "gpu_ready": gpu_srv, "gpu_base_mb": gpu_base,
                                "rounds": rows, "records": raw}
        finally:
            closed = srv.stop()
            result["server_stopped"] = {"port_closed": closed, "returncode": srv.proc.returncode}
            log(f"서버 종료: 포트 닫힘 {closed}")

    need_local = args.mode in ("direct", "encode", "all")
    probe = sampler = None
    if need_local:
        probe = EmbedProbe.install()
        result["warmup"] = probe.warmup
        result["gpu_after_model_load"] = nvidia_smi()
        sampler = ProcSampler().start()
        log(f"색인·모델 적재: {probe.warmup}")

    if args.mode in ("encode", "all"):
        assert probe is not None
        result["encode"] = encode_test(probe, args.encode_n, args.encode_repeats)

    ref: dict[str, dict[str, Any]] = {}
    if args.mode in ("direct", "all"):
        assert probe is not None and sampler is not None
        t0 = time.perf_counter()
        ref = reference_pass(uniq, delays, probe)
        result["reference"] = {"n": len(ref), "elapsed_s": round(time.perf_counter() - t0, 2),
                               "compute_s": stats(r["run_s"] for r in ref.values()),
                               "errors": sum(1 for r in ref.values() if r.get("error")),
                               "by_key": {k: {"digest": r["fingerprint"]["digest"] if r.get("fingerprint") else None,
                                              "stage_states": r.get("stage_states"), "n_cards": (r.get("fingerprint") or {}).get("n_cards")}
                                          for k, r in ref.items()}}
        log(f"기준(지연 0 순차) {len(ref)}건: {result['reference']['compute_s']}")
        gpu_base = (nvidia_smi() or {}).get("mem_used_mb")
        rows, raw = [], []
        for n in ns:
            log(f"direct N={n} 시작")
            rnd = run_round_direct(texts[n], delays, args.delay_scale, probe, sampler)
            row = summarize_round(rnd, ref, gpu_base)
            rows.append(row)
            raw.append(rnd["records"])
            log(f"direct N={n}: 성공 {row['ok']}/{n} 총시간 {row['total_s']} 처리량 {row['throughput_per_min']}/분 "
                f"GPU {row['gpu_mem_max_mb']} RAM {row['proc']['rss_max_mb']}MB 지문불일치 {row['fingerprint_mismatch']}")
        result["direct"] = {"gpu_base_mb": gpu_base, "rounds": rows, "records": raw}
        if args.compute_only:
            crow = []
            for n in ns:
                rnd = run_round_direct(texts[n], delays, 0.0, probe, sampler)
                crow.append(summarize_round(rnd, ref, gpu_base))
                log(f"compute-only N={n}: 전체 {rnd['makespan_s']}s 처리량 {crow[-1]['throughput_per_min']}/분")
            result["compute_only"] = {"rounds": crow}

    if sref and ref:  # 서버 기준과 직접 기준의 지문이 같아야 한다(같은 본문, 결정적)
        result["server_reference"]["mismatch_vs_direct_reference"] = sum(
            1 for k, r in sref.items() if k in ref and r.get("fingerprint") and ref[k].get("fingerprint")
            and r["fingerprint"]["digest"] != ref[k]["fingerprint"]["digest"])
        result["server_reference"]["compared_with_direct"] = sum(1 for k in sref if k in ref)

    result["gpu_end"] = nvidia_smi()
    result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    for key, label in (("direct", "직접 호출(스레드)"), ("server", f"서버({args.port}, {args.endpoint})")):
        if key in result:
            print("\n" + table(result[key]["rounds"], label) + "\n\n" + stage_table(result[key]["rounds"], label))
    if "compute_only" in result:
        print("\n" + table(result["compute_only"]["rounds"], "직접 호출, 지연 0(계산만)"))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        log(f"결과 JSON: {args.out}")
    if sampler:
        sampler.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
