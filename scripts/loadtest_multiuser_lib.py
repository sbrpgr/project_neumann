"""E4-L2e 다중 사용자 부하 시험 공용 부품(직접 호출·서버 모드가 같이 쓴다).

- `DelayedMockProvider`: mock provider에 과제(task)별 지연을 넣는다(실제 OpenAI는 부르지 않는다).
- `block_openai()`: OpenAIProvider 호출을 막는 안전장치(시험 중 실수로 provider가 openai가 돼도 네트워크로 안 나간다).
- `EmbedProbe`: bge-m3 임베딩 락을 시간 재는 락으로 바꿔 대기·점유 시간을 잰다(스레드별·전체).
- `ProcSampler`: 이 프로세스의 메모리(작업 집합)·CPU·스레드 수·GIL 지연·torch CUDA 최대 할당을 표본으로 잰다.
- `GpuPoller`: nvidia-smi로 GPU 전체 메모리·사용률을 폴링한다(다른 프로세스 몫 포함, 시작 전 기준값을 따로 잰다).
- 계획서 변형(`plan_bases`, `variant_text`), 결과 지문(`fingerprint`), 요약 통계(`stats`).

표준 라이브러리 + 저장소 패키지만 쓴다(psutil 없음: Windows는 ctypes, 그 밖은 resource).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from neumann.analyze.mock_responders import default_responders
from neumann.llm import FAIL_TIMEOUT, LLMCall, LLMResult, MockProvider

ROOT = Path(__file__).resolve().parent.parent

# 과제별 mock 지연(초, 균등 분포 lo~hi). 합계가 라이브 1건 약 60초에 가깝게(E5-L0e2e 라이브 61~69초):
# 적합성 5 + 검색어 3 + 지적 추출(묶음 23~29개, 24개씩 병렬 → 2~5초 × 2파) 약 8 + 카드 합성 10
# + 예상 심사평 10 + 체크리스트 10 + 2차 검증 10(카드가 많으면 호출 2번) ≈ 56~66초.
DEFAULT_DELAYS: dict[str, tuple[float, float]] = {
    "fitness": (4.0, 6.0),
    "query_axes": (2.5, 3.5),
    "extract_issues": (2.0, 5.0),
    "synthesize_cards": (9.0, 11.0),
    "expected_review": (9.0, 11.0),
    "checklist": (9.0, 11.0),
    "semantic_validate": (9.0, 11.0),
}


def parse_delays(items: Iterable[str] | None, base: dict[str, tuple[float, float]] | None = None) -> dict[str, tuple[float, float]]:
    """`task=3` 또는 `task=2:5` 목록 → 지연 표(기본값 위에 덮어씀). 모르는 task도 받는다(새 단계 대비)."""
    out = dict(DEFAULT_DELAYS if base is None else base)
    for raw in items or ():
        name, sep, val = raw.partition("=")
        if not sep or not name.strip():
            raise ValueError(f"지연 형식은 task=초 또는 task=최소:최대: {raw!r}")
        lo_s, _, hi_s = val.partition(":")
        lo = float(lo_s)
        hi = float(hi_s) if hi_s else lo
        if lo < 0 or hi < lo:
            raise ValueError(f"지연 범위가 틀렸다: {raw!r}")
        out[name.strip()] = (lo, hi)
    return out


class CallStats:
    """provider 호출 통계(스레드 안전): 과제별 호출 수·지연 합·입력 글자 수."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.by_task: dict[str, dict[str, float]] = {}
        self.max_inflight = 0
        self._inflight = 0

    def begin(self) -> None:
        with self._lock:
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)

    def end(self, task: str, delay: float, chars: int, ok: bool) -> None:
        with self._lock:
            self._inflight -= 1
            row = self.by_task.setdefault(task, {"calls": 0, "delay_s": 0.0, "chars": 0, "failed": 0})
            row["calls"] += 1
            row["delay_s"] += delay
            row["chars"] += chars
            row["failed"] += 0 if ok else 1

    def totals(self) -> dict[str, Any]:
        with self._lock:
            calls = sum(int(r["calls"]) for r in self.by_task.values())
            chars = sum(int(r["chars"]) for r in self.by_task.values())
            return {
                "calls": calls,
                "chars": chars,
                "failed": sum(int(r["failed"]) for r in self.by_task.values()),
                "delay_s": round(sum(r["delay_s"] for r in self.by_task.values()), 3),
                "max_inflight": self.max_inflight,
                "by_task": {k: {**v, "delay_s": round(v["delay_s"], 3)} for k, v in sorted(self.by_task.items())},
            }


class DelayedMockProvider(MockProvider):
    """결정적 mock 응답 + 과제별 지연(time.sleep, GIL을 놓는다 — 네트워크 대기와 같은 성질).

    지연이 호출 상한(call.timeout_s)보다 길면 실제 provider처럼 상한만큼 기다리고 timeout 실패를 돌려준다.
    결과의 생성 주체는 mock 그대로다(astra로 적지 않는다).
    """

    name = "mock"

    def __init__(
        self,
        delays: dict[str, tuple[float, float]] | None = None,
        *,
        scale: float = 1.0,
        seed: int = 0,
        stats: CallStats | None = None,
        sleep=time.sleep,
    ) -> None:
        super().__init__(default_responders())
        self.delays = dict(DEFAULT_DELAYS if delays is None else delays)
        self.scale = float(scale)
        self.stats = stats or CallStats()
        self._rng = random.Random(seed)
        self._rng_lock = threading.Lock()
        self._sleep = sleep

    def _delay(self, task: str) -> float:
        lo, hi = self.delays.get(task, (0.0, 0.0))
        with self._rng_lock:
            return self._rng.uniform(lo, hi) * self.scale

    def complete_json(self, call: LLMCall) -> LLMResult:
        delay = self._delay(call.task)
        chars = len(call.instructions) + len(call.input_text())
        self.stats.begin()
        ok = False
        try:
            limit = call.timeout_s
            if limit and delay > limit:
                self._sleep(limit)
                return LLMResult(ok=False, data=None, provider=self.name, model=self.model, task=call.task,
                                 effort=call.effort, error=FAIL_TIMEOUT, detail=f"{limit:.0f}s 상한(mock 지연)",
                                 latency_s=limit)
            if delay > 0:
                self._sleep(delay)
            res = super().complete_json(call)
            res.latency_s = delay
            ok = res.ok
            return res
        finally:
            self.stats.end(call.task, delay, chars, ok)


def block_openai() -> None:
    """안전장치: 이 프로세스에서 OpenAIProvider.complete_json이 불리면 예외(네트워크로 나가지 않는다)."""
    from neumann import llm as llm_mod

    def _refuse(self, call):  # noqa: ANN001
        raise RuntimeError("E4-L2e 부하 시험은 실제 OpenAI를 부르지 않는다(mock 전용)")

    llm_mod.OpenAIProvider.complete_json = _refuse  # type: ignore[method-assign]


def require_mock_env() -> None:
    """NEUMANN_LLM_PROVIDER=mock이 명시돼 있어야 시작한다(이 PC 환경에 openai 값이 남아 있을 수 있다)."""
    if os.environ.get("NEUMANN_LLM_PROVIDER", "").lower() != "mock":
        raise SystemExit("NEUMANN_LLM_PROVIDER=mock을 명시하고 다시 실행하라(실제 OpenAI 호출 금지)")


# ── 임베딩 락 계측 ─────────────────────────────────────────────────────────


class TimedLock:
    """threading.Lock 대신 쓰는 계측 락. 스레드별(threading.local)·전체 대기·점유 시간을 잰다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._meta = threading.Lock()
        self.local = threading.local()
        self.calls = 0
        self.wait_total = 0.0
        self.wait_max = 0.0
        self.hold_total = 0.0
        self.hold_max = 0.0
        self.waiting = 0
        self.max_waiting = 0

    def __enter__(self) -> TimedLock:
        with self._meta:
            self.waiting += 1
            self.max_waiting = max(self.max_waiting, self.waiting)
        t0 = time.perf_counter()
        self._lock.acquire()
        wait = time.perf_counter() - t0
        with self._meta:
            self.waiting -= 1
        self.local.t_acq = time.perf_counter()
        self.local.wait = getattr(self.local, "wait", 0.0) + wait
        self.local.n = getattr(self.local, "n", 0) + 1
        with self._meta:
            self.calls += 1
            self.wait_total += wait
            self.wait_max = max(self.wait_max, wait)
        return self

    def __exit__(self, *exc: object) -> None:
        hold = time.perf_counter() - self.local.t_acq
        self.local.hold = getattr(self.local, "hold", 0.0) + hold
        self._lock.release()
        with self._meta:
            self.hold_total += hold
            self.hold_max = max(self.hold_max, hold)

    # threading.Lock과 같은 이름도 둔다(혹시 acquire/release로 부르는 코드가 있으면)
    def acquire(self, *a: Any, **k: Any) -> bool:
        self.__enter__()
        return True

    def release(self) -> None:
        self.__exit__(None, None, None)

    def thread_totals(self) -> dict[str, float]:
        return {"n": getattr(self.local, "n", 0), "wait": getattr(self.local, "wait", 0.0),
                "hold": getattr(self.local, "hold", 0.0)}

    def reset(self) -> None:
        with self._meta:
            self.calls = 0
            self.wait_total = self.wait_max = self.hold_total = self.hold_max = 0.0
            self.max_waiting = self.waiting

    def snapshot(self) -> dict[str, Any]:
        with self._meta:
            return {"calls": self.calls, "wait_total_s": round(self.wait_total, 4), "wait_max_s": round(self.wait_max, 4),
                    "hold_total_s": round(self.hold_total, 4), "hold_max_s": round(self.hold_max, 4),
                    "max_waiting": self.max_waiting}


class EmbedProbe:
    """공유 bge-m3 임베더의 `_lock`을 TimedLock으로 바꾼다. 임베더가 락을 안 쓰는 구현이면 끈다."""

    def __init__(self, embedder: Any) -> None:
        self.embedder = embedder
        self.lock: TimedLock | None = None
        if embedder is not None and hasattr(embedder, "_lock"):
            self.lock = TimedLock()
            embedder._lock = self.lock

    @classmethod
    def install(cls) -> EmbedProbe:
        """색인·임베딩 모델을 올리고(search.warmup) 계측 락을 건다."""
        from neumann.index import search

        info = search.warmup()
        emb, _ = search._query_embedder(search.get_store())  # noqa: SLF001 — 같은 캐시 인스턴스
        probe = cls(emb)
        probe.warmup = info
        return probe

    def thread_totals(self) -> dict[str, float]:
        return self.lock.thread_totals() if self.lock else {"n": 0, "wait": 0.0, "hold": 0.0}

    def reset(self) -> None:
        if self.lock:
            self.lock.reset()

    def snapshot(self) -> dict[str, Any]:
        return self.lock.snapshot() if self.lock else {"calls": 0, "note": "계측 락 없음"}


# ── 프로세스 자원 표본 ─────────────────────────────────────────────────────


def _win_mem() -> tuple[int, int] | None:
    """(현재 작업 집합, 최대 작업 집합) 바이트. Windows가 아니면 None."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return None
    return int(pmc.WorkingSetSize), int(pmc.PeakWorkingSetSize)


def process_memory() -> tuple[int, int]:
    """(현재, 프로세스 수명 최대) 상주 메모리 바이트."""
    win = _win_mem()
    if win is not None:
        return win
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
        return peak, peak
    except Exception:  # noqa: BLE001
        return 0, 0


def system_cpu_times() -> tuple[float, float] | None:
    """(유휴, 전체) 초. Windows는 GetSystemTimes, 리눅스는 /proc/stat. 없으면 None."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        idle, kern, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.WinDLL("kernel32").GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
            return None

        def sec(ft: Any) -> float:
            return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7

        return sec(idle), sec(kern) + sec(user)  # 커널 시간에 유휴가 포함된다
    try:
        parts = [float(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        return parts[3] + parts[4], sum(parts)
    except Exception:  # noqa: BLE001
        return None


class ProcSampler:
    """이 프로세스의 자원 표본(간격 interval초) + GIL 지연 탐침(5ms 잠들고 깨어나는 데 걸린 초과 시간)."""

    def __init__(self, interval: float = 0.5, gil_probe_s: float = 0.005) -> None:
        self.interval = interval
        self.gil_probe_s = gil_probe_s
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.t0 = time.perf_counter()
            self.cpu0 = time.process_time()
            self.sys0 = system_cpu_times()
            self.mem_max = process_memory()[0]
            self.mem_start = self.mem_max
            self.cores_max = 0.0
            self.sys_cpu_max = 0.0
            self.threads_max = threading.active_count()
            self.gil: list[float] = []
            self._last = (time.perf_counter(), time.process_time(), system_cpu_times())
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
        except Exception:  # noqa: BLE001
            pass

    def start(self) -> ProcSampler:
        for fn in (self._sample_loop, self._gil_loop):
            t = threading.Thread(target=fn, daemon=True, name=f"sampler-{fn.__name__}")
            t.start()
            self._threads.append(t)
        return self

    def stop(self) -> None:
        self._stop.set()

    def _sample_loop(self) -> None:
        while not self._stop.wait(self.interval):
            now, cpu, sysc = time.perf_counter(), time.process_time(), system_cpu_times()
            mem = process_memory()[0]
            with self._lock:
                t_prev, cpu_prev, sys_prev = self._last
                dt = max(1e-6, now - t_prev)
                self.cores_max = max(self.cores_max, (cpu - cpu_prev) / dt)
                if sysc and sys_prev and sysc[1] > sys_prev[1]:
                    busy = 1.0 - (sysc[0] - sys_prev[0]) / (sysc[1] - sys_prev[1])
                    self.sys_cpu_max = max(self.sys_cpu_max, busy * 100.0)
                self.mem_max = max(self.mem_max, mem)
                self.threads_max = max(self.threads_max, threading.active_count())
                self._last = (now, cpu, sysc)

    def _gil_loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.perf_counter()
            time.sleep(self.gil_probe_s)
            late = time.perf_counter() - t0 - self.gil_probe_s
            with self._lock:
                self.gil.append(late)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            wall = max(1e-6, time.perf_counter() - self.t0)
            cpu = time.process_time() - self.cpu0
            sysc = system_cpu_times()
            sys_avg = None
            if sysc and self.sys0 and sysc[1] > self.sys0[1]:
                sys_avg = round(100.0 * (1.0 - (sysc[0] - self.sys0[0]) / (sysc[1] - self.sys0[1])), 1)
            gil = sorted(self.gil)
            out: dict[str, Any] = {
                "wall_s": round(wall, 3),
                "cpu_s": round(cpu, 3),
                "cores_avg": round(cpu / wall, 3),
                "cores_max": round(self.cores_max, 3),
                "sys_cpu_avg_pct": sys_avg,
                "sys_cpu_max_pct": round(self.sys_cpu_max, 1),
                "n_cpus": os.cpu_count(),
                "rss_start_mb": round(self.mem_start / 2**20, 1),
                "rss_max_mb": round(max(self.mem_max, process_memory()[0]) / 2**20, 1),
                "rss_peak_lifetime_mb": round(process_memory()[1] / 2**20, 1),
                "threads_max": self.threads_max,
                "gil_probe_ms": {
                    "n": len(gil),
                    "p50": round(1000 * pct(gil, 50), 2),
                    "p99": round(1000 * pct(gil, 99), 2),
                    "max": round(1000 * (gil[-1] if gil else 0.0), 2),
                },
            }
        try:
            import torch

            if torch.cuda.is_available():
                out["torch_cuda_max_alloc_mb"] = round(torch.cuda.max_memory_allocated() / 2**20, 1)
                out["torch_cuda_max_reserved_mb"] = round(torch.cuda.max_memory_reserved() / 2**20, 1)
        except Exception:  # noqa: BLE001
            pass
        return out


# ── GPU(nvidia-smi) ────────────────────────────────────────────────────────


def nvidia_smi() -> dict[str, Any] | None:
    """GPU 전체 메모리 사용(MiB)·사용률(%)·계산 프로세스 수. nvidia-smi가 없으면 None."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip().splitlines()[0]
        used, total, util = (float(x) for x in out.split(","))
        apps = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.split()
        return {"mem_used_mb": used, "mem_total_mb": total, "util_pct": util, "compute_pids": [int(p) for p in apps if p.isdigit()]}
    except Exception:  # noqa: BLE001
        return None


class GpuPoller:
    """nvidia-smi 폴링(간격 interval초). 최대 메모리·사용률 최대/평균."""

    def __init__(self, interval: float = 1.0) -> None:
        self.interval = interval
        self.samples: list[tuple[float, float]] = []
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def __enter__(self) -> GpuPoller:
        self._t = threading.Thread(target=self._loop, daemon=True, name="gpu-poller")
        self._t.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._t:
            self._t.join(timeout=15)

    def _loop(self) -> None:
        while True:
            s = nvidia_smi()
            if s:
                self.samples.append((s["mem_used_mb"], s["util_pct"]))
            if self._stop.wait(self.interval):
                return

    def summary(self) -> dict[str, Any]:
        if not self.samples:
            return {"samples": 0}
        mem = [m for m, _ in self.samples]
        util = [u for _, u in self.samples]
        return {"samples": len(self.samples), "mem_max_mb": max(mem), "util_max_pct": max(util),
                "util_avg_pct": round(sum(util) / len(util), 1)}


# ── 계획서 변형 ────────────────────────────────────────────────────────────


def plan_bases(root: Path = ROOT) -> list[tuple[str, str]]:
    """(이름, 본문): 데모 계획서 3건 → 채운 예시 2건 → 템플릿 골격 5건(범위 밖 음성 대조는 뺀다)."""
    files = sorted((root / "tests" / "fixtures" / "plans").glob("plan*.md"))
    files += sorted((root / "src" / "neumann" / "api" / "templates" / "examples").glob("*.md"))
    files += sorted((root / "src" / "neumann" / "api" / "templates").glob("*.md"))
    return [(p.stem, p.read_text(encoding="utf-8")) for p in files]


def variant_text(base: str, tag: str, k: int) -> str:
    """캐시 적중을 피하려고 끝에 한 줄을 덧붙인다(한글·숫자만: 영문 검색어를 바꾸지 않게)."""
    return base.rstrip("\n") + f"\n\n부하 시험 변형 {tag} 사용자 {k + 1}번 메모.\n"


def round_texts(bases: list[tuple[str, str]], n: int, tag: str) -> list[tuple[str, str]]:
    """동시 n명의 (기반 이름, 본문). 사용자 k는 기반 k mod 개수 + 변형 줄."""
    return [(bases[k % len(bases)][0], variant_text(bases[k % len(bases)][1], tag, k)) for k in range(n)]


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ── 결과 지문·검색 상태 섞임 ───────────────────────────────────────────────


def fingerprint(result: Any) -> dict[str, Any]:
    """동시 실행과 순차 실행을 비교할 지문. 결과(PremortemResult 또는 그 JSON dict)에서 만든다."""
    d = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
    core = {
        "similar": [(w["work_id"], round(float(w["similarity"]), 4)) for w in d.get("similar_works", [])],
        "cards": [(c["risk_code"], list(c.get("evidence", []))) for c in d.get("risk_cards", [])],
        "checklist": len(d.get("checklist") or []),
        "stages": [(s.get("stage"), s.get("state")) for s in d.get("stages", [])],
    }
    digest = hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    return {"digest": digest, "n_similar": len(core["similar"]), "n_cards": len(core["cards"]),
            "n_checklist": core["checklist"], "status_mixup": search_status_mixup(d)}


def search_status_mixup(d: dict[str, Any]) -> bool:
    """`plan_checks.search.backend_status`가 이 요청의 검색 결과와 맞지 않는가(전역 last_search_status 경쟁).

    같은 요청이면 backend_status.n_hits == len(scores)이고 top_score == scores[0](결합 순서 첫 편)이다.
    """
    s = (d.get("plan_checks") or {}).get("search") or {}
    bs = s.get("backend_status") or {}
    scores = s.get("scores") or []
    if not bs or "n_hits" not in bs:
        return False
    if int(bs["n_hits"]) != len(scores):
        return True
    top = bs.get("top_score")
    if scores and top is not None and abs(float(top) - float(scores[0])) > 1e-3:
        return True
    return False


def stage_states(d: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in d.get("stages", []):
        st = s.get("state") or s.get("status")
        out[st] = out.get(st, 0) + 1
    return out


# ── 통계 ──────────────────────────────────────────────────────────────────


def pct(sorted_vals: list[float], q: float) -> float:
    """정렬된 값의 백분위(최근접 순위)."""
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, max(0, int(round(q / 100.0 * (len(sorted_vals) - 1)))))
    return float(sorted_vals[i])


def stats(vals: Iterable[float]) -> dict[str, float]:
    v = sorted(float(x) for x in vals)
    if not v:
        return {"n": 0}
    return {"n": len(v), "min": round(v[0], 3), "p50": round(pct(v, 50), 3), "mean": round(sum(v) / len(v), 3),
            "p95": round(pct(v, 95), 3), "max": round(v[-1], 3)}


__all__ = [
    "DEFAULT_DELAYS",
    "CallStats",
    "DelayedMockProvider",
    "EmbedProbe",
    "GpuPoller",
    "ProcSampler",
    "TimedLock",
    "block_openai",
    "fingerprint",
    "nvidia_smi",
    "parse_delays",
    "pct",
    "plan_bases",
    "process_memory",
    "require_mock_env",
    "round_texts",
    "search_status_mixup",
    "stage_states",
    "stats",
    "text_key",
    "variant_text",
]
