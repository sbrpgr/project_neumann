"""SEC-7 저부하 로컬 실측: python -m tests.e4.sec7_probe. 네트워크·제품 LLM 호출 없음."""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path


def _peak_memory() -> dict[str, float]:
    if os.name != "nt":
        import resource

        return {"peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                         "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                                         "PagefileUsage", "PeakPagefileUsage")]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise OSError("own-worker memory measurement failed")
    return {"peak_rss_mb": round(counters.PeakWorkingSetSize / 1024**2, 2),
            "peak_commit_mb": round(counters.PeakPagefileUsage / 1024**2, 2)}


def _pdf_child() -> None:
    from neumann.api import upload

    upload._deny_disk_writes()
    limited = upload._limit_worker_memory(512)
    if not limited:
        raise RuntimeError("memory limit unavailable")
    data = sys.stdin.buffer.read(upload.MAX_UPLOAD_BYTES + 1)
    start = time.perf_counter()
    try:
        result = upload.extract_plan("probe.pdf", data, deadline_s=10)
        output = {"status": 200, "chars": len(result.text), "lines": result.lines,
                  "pages": result.pages, "warnings": len(result.warnings)}
    except upload.UploadRejected as exc:
        output = {"status": exc.status_code, "reason": exc.message}
    output.update(memory_limited=limited, extraction_ms=round((time.perf_counter() - start) * 1000, 2), **_peak_memory())
    sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False).encode("utf-8"))


def median_ms(fn, repeats=3):
    elapsed = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        elapsed.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(elapsed), 3)


def run() -> None:
    # 프로세스 범위만 설정. 키는 읽거나 복원하지 않는다.
    os.environ["NEUMANN_LLM_PROVIDER"] = "mock"
    os.environ["NEUMANN_LIVE_TESTS"] = "0"
    os.environ.pop("NEUMANN_LIVE_LLM_OK", None)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from fastapi.testclient import TestClient

    from neumann.api import export, serving, upload
    from tests.e4.test_export import fixture_result
    from tests.e4.test_sec7 import package_app, pdf_with_streams
    from tests.e4.test_upload import KOREAN_LINES, make_pdf

    root = Path(__file__).resolve().parents[2]
    for folder in (root / "tests/fixtures/plans", root / "src/neumann/api/templates",
                   root / "src/neumann/api/templates/examples"):
        for path in sorted(folder.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            print(json.dumps({"sample": str(path.relative_to(root)), "lines": serving.count_lines(text),
                              "chars": len(text)}, ensure_ascii=False))

    tokens = [f"ProbeJob_{i:06d}_" + "aB7_" * 4 for i in range(500)]
    assert all(len(token) == 32 for token in tokens)
    for token in tokens:
        serving.register_log_secret(token)
    try:
        for size in (1024, 2048, 4096, 8192, 16384, 32768, 65536):
            text = ("abc123 " * (size // 7 + 1))[:size] + "+".join(tokens[-1])
            masked = serving.mask_live_secrets(text)
            assert tokens[-1] not in masked and masked.endswith(tokens[-1][:6] + "…")
            print(json.dumps({"mask_chars": size, "live_ids": 500, "median_ms": median_ms(lambda: serving.mask_live_secrets(text))}))
    finally:
        for token in tokens:
            serving.forget_log_secret(token)

    c = TestClient(package_app()[0])
    card = {"why_applies": {"plan_lines": list(range(1, 200))}}
    for count in (3300, 4000):
        payload = {"result": {"risk_cards": [card] * count}}
        raw = json.dumps(payload, ensure_ascii=False).encode()
        start = time.perf_counter()
        response = c.post("/premortem/package", content=raw, headers={"content-type": "application/json"})
        print(json.dumps({"package_cards": count, "input_bytes": len(raw), "status": response.status_code,
                          "elapsed_ms": round((time.perf_counter() - start) * 1000, 2)}))
        assert response.status_code == 422

    def old_edges(refs):
        by_line = {}
        for ref, card in refs:
            for no in card.why_applies.plan_lines:
                attached = by_line.setdefault(no, [])
                if ref not in attached:
                    attached.append(ref)
        return by_line

    def new_edges(refs):
        by_line = {}
        for ref, card in refs:
            for no in dict.fromkeys(card.why_applies.plan_lines):
                by_line.setdefault(no, []).append(ref)
        return by_line

    card_model = fixture_result().risk_cards[0].model_copy(deep=True)
    card_model.why_applies.plan_lines = list(range(1, 101))
    for count in (500, 1000):
        refs = [(f"C{i}", card_model) for i in range(count)]
        assert old_edges(refs) == new_edges(refs)
        print(json.dumps({"annotation_cards": count, "refs_each": 100,
                          "old_ms": median_ms(lambda: old_edges(refs), repeats=1),
                          "new_ms": median_ms(lambda: new_edges(refs), repeats=1)}))

    pdfs = {
        "normal_12_pages": make_pdf([KOREAN_LINES] * 12),
        "page_stream_skip": pdf_with_streams([None, b"%" + b"x" * upload.MAX_PDF_PAGE_STREAM]),
        "decode_bomb_skip": pdf_with_streams([None, b"%" + b"x" * upload.MAX_PDF_STREAM_DECODE]),
        "total_stream_reject": pdf_with_streams([b"%" + b"x" * 899998 + b"\n"] * 6),
        "page_chars_reject": make_pdf([["x" * 20001]]),
    }
    command = [sys.executable, "-I", "-B", "-c",
               f"import sys; sys.path[:0] = [{str(root)!r}, {str(root / 'src')!r}]; from tests.e4.sec7_probe import _pdf_child; _pdf_child()"]
    for name, data in pdfs.items():
        start = time.perf_counter()
        proc = subprocess.run(command, input=data, capture_output=True, timeout=12, env=upload._worker_env(),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert proc.returncode == 0, f"probe worker failed: {name}"
        result = json.loads(proc.stdout)
        print(json.dumps({"pdf": name, "input_bytes": len(data),
                          "wall_ms": round((time.perf_counter() - start) * 1000, 2), **result}, ensure_ascii=False))


if __name__ == "__main__":
    run()
