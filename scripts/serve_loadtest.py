"""부하 시험(E4-L2c): 감시 스크립트로 가짜 느린 파이프라인 서버를 띄우고 동시 요청을 넣어 대기열·캐시·속도 제한·재시작을 본다.

실제 분석(bge-m3·OpenAI)은 부르지 않는다(scripts/serve_fake_app.py). 결과 캐시·감시 로그는 임시 폴더에 쓰고 지운다.

    python scripts/serve_loadtest.py --port 8122 --out docs/reports/E4-L2c_loadtest.txt

시나리오
  A 동시 10건(서로 다른 계획서·IP): 동시 상한 2, 나머지는 대기 순번 1~8로 차례대로
  B 같은 10건 다시: 모두 캐시 적중(즉시)
  C 동시 12건(대기열 상한 8): 2 실행 + 8 대기 + 2건 503(사용자 문구)
  D 한 IP에서 7건: 분당 6건 넘는 1건 429(사용자 문구)
  E 데모 계획서 1건 → 디스크 캐시(허용 목록). 사용자 입력 결과는 디스크에 0개(메모리만)
  F 서버 강제 종료(/__crash) → 감시 스크립트가 다시 띄움 → 데모는 디스크 캐시로 즉시, 사용자 입력은 다시 분석
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
PLAN = (ROOT / "tests" / "fixtures" / "plans" / "plan.md").read_text(encoding="utf-8")
OUT: list[str] = []
T0 = time.monotonic()


def say(msg: str = "") -> None:
    line = f"[+{time.monotonic() - T0:6.2f}s] {msg}" if msg else ""
    OUT.append(line)
    print(line, flush=True)


def plan_text(tag: str) -> str:
    return PLAN if tag == "DEMO" else f"{PLAN}\n\n부하 시험 계획서 변형: {tag}\n"


def post(base: str, tag: str, ticket: str, ip: str) -> dict[str, Any]:
    t = time.monotonic()
    with httpx.Client(base_url=base, timeout=120) as c:
        r = c.post("/premortem/view", json={"plan_text": plan_text(tag)},
                   headers={"X-Neumann-Ticket": ticket, "X-Forwarded-For": ip})
    body = r.json()
    sv = (body.get("_status") or {}).get("serving") or {}
    return {"ticket": ticket, "code": r.status_code, "cache": r.headers.get("x-neumann-cache"),
            "pos": sv.get("position_at_arrival", r.headers.get("x-neumann-queue-position")),
            "waited": sv.get("waited_s"), "total": round(time.monotonic() - t, 2),
            "message": body.get("message", ""), "retry_after": r.headers.get("retry-after")}


def poll_queue(base: str, tickets: list[str], stop: threading.Event, every: float = 0.5) -> None:
    last = None
    with httpx.Client(base_url=base, timeout=5) as c:
        while not stop.is_set():
            try:
                st = c.get("/queue/status").json()
                pos = {}
                for t in tickets:
                    tk = c.get("/queue/status", params={"ticket": t}).json()["ticket"]
                    if tk["state"] == "waiting":
                        pos[t[-2:]] = f"{tk['position']}번째/{tk['eta_s']}s"
                    elif tk["state"] == "running":
                        pos[t[-2:]] = "실행"
                snap = (st["active"], st["waiting"], tuple(sorted(pos.items())))
                if snap != last:
                    say(f"  queue active={st['active']} waiting={st['waiting']} eta_new={st['eta_new_s']}s "
                        f"| {' '.join(f'{k}:{v}' for k, v in sorted(pos.items()))}")
                    last = snap
            except (httpx.HTTPError, ValueError, KeyError):
                pass
            stop.wait(every)


def burst(base: str, name: str, items: list[tuple[str, str, str]], poll: bool = True) -> list[dict[str, Any]]:
    """items: (계획서 태그, ticket, ip). 동시에 보낸다."""
    say(f"== {name}: 동시 {len(items)}건")
    stop = threading.Event()
    th = threading.Thread(target=poll_queue, args=(base, [t for _, t, _ in items], stop), daemon=True)
    if poll:
        th.start()
    with ThreadPoolExecutor(max_workers=len(items)) as ex:
        futs = []
        for tag, ticket, ip in items:
            futs.append(ex.submit(post, base, tag, ticket, ip))
            time.sleep(0.05)  # 도착 순서를 분명히
        res = [f.result() for f in futs]
    stop.set()
    if poll:
        th.join(2)
    for r in res:
        extra = f" retry_after={r['retry_after']} msg=\"{r['message']}\"" if r["code"] != 200 else ""
        say(f"  {r['ticket']} code={r['code']} cache={r['cache']} 도착순번={r['pos']} 대기={r['waited']}s "
            f"총={r['total']}s{extra}")
    codes: dict[int, int] = {}
    for r in res:
        codes[r["code"]] = codes.get(r["code"], 0) + 1
    say(f"  요약 {name}: {json.dumps(codes)} 최장={max(r['total'] for r in res)}s")
    return res


def wait_health(base: str, timeout: float = 90) -> float:
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        try:
            if httpx.get(base + "/health", timeout=3).status_code == 200:
                return time.monotonic() - t
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise SystemExit("서버가 뜨지 않았다")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8122)
    ap.add_argument("--run-s", type=float, default=2.0, help="가짜 분석 시간(초)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.port == 8010:
        raise SystemExit("8010은 대표 점검 서버 포트라 쓰지 않는다")
    base = f"http://127.0.0.1:{a.port}"
    tmp = Path(tempfile.mkdtemp(prefix="neumann_e4l2c_"))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", NEUMANN_PUBLIC="1", NEUMANN_WARMUP="0",
               NEUMANN_FAKE_RUN_S=str(a.run_s), NEUMANN_AVG_RUN_S=str(a.run_s), NEUMANN_MAX_CONCURRENT="2",
               NEUMANN_QUEUE_MAX="8", NEUMANN_RATE_PER_MIN="6", NEUMANN_RESULT_CACHE_DIR=str(tmp / "results"),
               NEUMANN_BUDGET_FILE=str(tmp / "budget.json"), NEUMANN_BLOCK_FILE=str(tmp / "block.flag"),
               NEUMANN_DAILY_BUDGET="100", NEUMANN_FAKE_CRASH="1")
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT)])
    server_log = tmp / "server_stdout.log"
    cmd = [sys.executable, str(ROOT / "scripts" / "serve.py"), "--app", "scripts.serve_fake_app:app",
           "--port", str(a.port), "--interval", "1", "--fails", "2", "--startup-grace", "60",
           "--log-file", str(tmp / "serve.log")]
    say(f"감시 스크립트 시작: serve.py --app scripts.serve_fake_app:app --port {a.port} "
        f"(동시 2, 대기열 8, 분당 6건, 가짜 분석 {a.run_s}s)")
    with server_log.open("wb") as so:
        sup = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=so, stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
    try:
        say(f"health 정상까지 {wait_health(base):.1f}s")
        # A
        a_items = [(f"A{i:02d}", f"tk_A_{i:02d}", f"198.51.100.{i + 1}") for i in range(10)]
        res_a = burst(base, "A 동시 10건(서로 다른 계획서·IP)", a_items)
        # B
        res_b = burst(base, "B 같은 10건 다시(캐시)", [(tag, t.replace("_A_", "_B_"), ip) for tag, t, ip in a_items],
                      poll=False)
        # C
        res_c = burst(base, "C 동시 12건(대기열 상한 8)",
                      [(f"C{i:02d}", f"tk_C_{i:02d}", f"203.0.113.{i + 1}") for i in range(12)])
        # D
        res_d = burst(base, "D 한 IP에서 7건(분당 6건)",
                      [(f"D{i:02d}", f"tk_D_{i:02d}", "192.0.2.77") for i in range(7)], poll=False)
        st = httpx.get(base + "/queue/status").json()
        say(f"카운터: {json.dumps(st['counters'], ensure_ascii=False)}")
        # E
        say("== E 데모 계획서(공개 입력) 1건 → 디스크 캐시")
        demo = post(base, "DEMO", "tk_E_demo", "198.51.100.200")
        rdir = tmp / "results"
        files = sorted(x.name for x in rdir.glob("*.json")) if rdir.exists() else []
        n_user = len(res_a) + len(res_c) + len(res_d)
        say(f"  데모: code={demo['code']} cache={demo['cache']} | 결과 캐시 폴더 파일 {len(files)}개 "
            f"(사용자 입력 {n_user}건 요청 뒤): {[f[:12] for f in files]}")
        body_hits = [f for f in rdir.glob("*.json") if "부하 시험 계획서 변형" in f.read_text(encoding="utf-8")]
        say(f"  디스크 파일 중 사용자 입력 본문 조각이 든 파일: {len(body_hits)}개")
        # F
        say("== F 서버 강제 종료 → 감시 스크립트 재시작")
        try:
            httpx.post(base + "/__crash", timeout=3)
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
        say(f"다시 health 정상까지 {wait_health(base):.1f}s")
        r = post(base, "DEMO", "tk_F_demo", "198.51.100.99")
        say(f"  재시작 뒤 데모 다시: code={r['code']} cache={r['cache']} 총={r['total']}s (디스크 캐시)")
        u = post(base, "A03", "tk_F_A03", "198.51.100.98")
        say(f"  재시작 뒤 사용자 입력 A03 다시: code={u['code']} cache={u['cache']} 총={u['total']}s "
            "(메모리 캐시는 재시작으로 비워짐 → 다시 분석)")
        ok = (all(x["code"] == 200 for x in res_a) and all(x["cache"] == "hit" for x in res_b)
              and sorted(x["code"] for x in res_c).count(503) == 2 and [x["code"] for x in res_d].count(429) == 1
              and max(x["pos"] or 0 for x in res_a) == 8 and len(files) == 1 and not body_hits
              and r["cache"] == "hit" and u["cache"] == "miss" and u["code"] == 200)
        say(f"판정: {'PASS' if ok else 'FAIL'}")
        rc = 0 if ok else 1
    finally:
        if os.name == "nt":
            sup.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            sup.send_signal(signal.SIGINT)
        try:
            sup.wait(timeout=20)
        except subprocess.TimeoutExpired:
            sup.kill()
        time.sleep(0.5)
        try:
            httpx.get(base + "/health", timeout=2)
            say("경고: 서버가 아직 떠 있다")
        except httpx.HTTPError:
            say(f"서버 종료 확인(포트 {a.port} 닫힘)")
        say("-- 감시 스크립트 로그(serve.log)")
        for line in (tmp / "serve.log").read_text(encoding="utf-8").splitlines():
            OUT.append("   " + line)
            print("   " + line)
        say("-- 서버 요청 로그(neumann.serving, 일부)")
        lines = server_log.read_text(encoding="utf-8", errors="replace").splitlines()
        req = [ln for ln in lines if "neumann.serving" in ln]
        for line in req[:14] + (["   ..."] if len(req) > 20 else []) + req[-6:]:
            OUT.append("   " + line)
            print("   " + line)
        leaks = [ln for ln in lines if "부하 시험 계획서 변형" in ln or "Traceback" in ln]
        say(f"서버 로그 {len(lines)}줄 중 계획서 본문·트레이스가 든 줄: {len(leaks)}")
        if a.out:
            Path(a.out).write_text("\n".join(OUT) + "\n", encoding="utf-8")
        if os.getenv("NEUMANN_LOADTEST_KEEP") == "1":
            say(f"임시 폴더 남김: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
