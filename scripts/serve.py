"""공개 라이브 서버 실행 + 감시(E4-L2c).

uvicorn(worker 1개)을 자식 프로세스로 띄우고 ``/health``를 주기적으로 본다. 프로세스가 죽었거나 health가
연속으로 실패하면 다시 띄운다. 재시작 횟수·시각·이유를 표준 출력과 로그 파일에 남긴다.

    python scripts/serve.py                                  # 127.0.0.1:8000, 공개 프로필(NEUMANN_PUBLIC=1)
    python scripts/serve.py --host 0.0.0.0 --port 8122
    python scripts/serve.py --app scripts.serve_fake_app:app --port 8122   # 가짜 느린 파이프라인(부하 시험)

- 기본으로 ``NEUMANN_PUBLIC=1``을 자식에 넘긴다: 속도 제한(분당 6건)·결과 캐시·시작 예열이 켜진다(``--no-public``로 끔).
- 터널(cloudflared·ngrok)은 이 서버의 host:port를 가리키게 한다. 대기열 상태는 프로세스 메모리에 있으므로 worker는 1개다.
- 로그 파일 기본값: ``<NEUMANN_DATA_DIR>/logs/serve.log``(공유 데이터 폴더, 저장소에 안 올라간다).
- 멈추기: Ctrl+C(Windows는 Ctrl+Break도). 자식도 같이 끝낸다.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WIN = os.name == "nt"


class Supervisor:
    def __init__(self, args: argparse.Namespace) -> None:
        self.a = args
        self.proc: subprocess.Popen[bytes] | None = None
        self.restarts = 0
        self.started_at = 0.0
        self.healthy_once = False
        data_dir = Path(os.getenv("NEUMANN_DATA_DIR") or ROOT / "data")
        self.log_path = Path(args.log_file) if args.log_file else data_dir / "logs" / "serve.log"
        check_host = "127.0.0.1" if args.host in {"0.0.0.0", "::", ""} else args.host
        self.health_url = f"http://{check_host}:{args.port}/health"

    # 로그 ------------------------------------------------------------
    def log(self, msg: str) -> None:
        line = f"[serve] {datetime.now().isoformat(timespec='seconds')} {msg}"
        print(line, flush=True)
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # 자식 ------------------------------------------------------------
    def child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        paths = [str(ROOT / "src"), str(ROOT)]
        if env.get("PYTHONPATH"):
            paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(paths)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        if not self.a.no_public:
            env.setdefault("NEUMANN_PUBLIC", "1")
        return env

    def start(self) -> None:
        cmd = [sys.executable, "-m", "uvicorn", self.a.app, "--host", self.a.host, "--port", str(self.a.port),
               "--workers", "1", "--timeout-graceful-shutdown", "5"]
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0
        self.proc = subprocess.Popen(cmd, cwd=ROOT, env=self.child_env(), creationflags=flags,
                                     start_new_session=not IS_WIN)
        self.started_at = time.monotonic()
        self.healthy_once = False
        self.log(f"시작 pid={self.proc.pid} app={self.a.app} host={self.a.host} port={self.a.port} "
                 f"재시작 누적={self.restarts}")

    def stop(self, why: str) -> None:
        p = self.proc
        if p is None or p.poll() is not None:
            return
        self.log(f"중지 pid={p.pid} ({why})")
        try:
            if IS_WIN:
                p.send_signal(signal.CTRL_BREAK_EVENT)  # uvicorn이 SIGBREAK를 받아 정상 종료
            else:
                p.send_signal(signal.SIGTERM)
            p.wait(timeout=8)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            p.kill()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def healthy(self) -> bool:
        try:
            with urllib.request.urlopen(self.health_url, timeout=self.a.health_timeout) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    # 감시 ------------------------------------------------------------
    def run(self) -> int:
        self.log(f"감시 시작 health={self.health_url} 주기={self.a.interval}s 연속실패={self.a.fails}회 "
                 f"시작유예={self.a.startup_grace}s 로그={self.log_path}")
        self.start()
        fails = 0
        t_end = time.monotonic() + self.a.run_for if self.a.run_for > 0 else None
        try:
            while True:
                time.sleep(self.a.interval)
                if t_end is not None and time.monotonic() >= t_end:
                    self.log("--run-for 시간이 끝나 멈춘다")
                    return 0
                assert self.proc is not None
                rc = self.proc.poll()
                if rc is not None:
                    reason = f"프로세스 종료(code={rc})"
                elif self.healthy():
                    if not self.healthy_once:
                        self.log(f"health 정상 (뜨는 데 {time.monotonic() - self.started_at:.1f}s)")
                    self.healthy_once, fails = True, 0
                    continue
                elif not self.healthy_once and time.monotonic() - self.started_at < self.a.startup_grace:
                    continue  # 모델·색인 로드 중
                else:
                    fails += 1
                    self.log(f"health 실패 {fails}/{self.a.fails}")
                    if fails < self.a.fails:
                        continue
                    reason = f"health 연속 실패 {fails}회"
                    self.stop(reason)
                fails = 0
                self.restarts += 1
                self.log(f"재시작 #{self.restarts} 이유: {reason}")
                if self.a.max_restarts and self.restarts > self.a.max_restarts:
                    self.log(f"재시작 상한 {self.a.max_restarts}회를 넘어 멈춘다")
                    return 1
                time.sleep(min(2 ** min(self.restarts - 1, 4), 15) if self.restarts > 3 else 0.5)
                self.start()
        except KeyboardInterrupt:
            self.log("중단 신호")
            return 0
        finally:
            self.stop("감시 종료")
            self.log(f"끝 재시작 누적={self.restarts}")


def _raise_kbi(*_: object) -> None:
    raise KeyboardInterrupt


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Neumann 라이브 서버 실행 + /health 감시·자동 재시작")
    ap.add_argument("--host", default=os.getenv("NEUMANN_API_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("NEUMANN_API_PORT", "8000")))
    ap.add_argument("--app", default="neumann.api.main:app", help="uvicorn 앱 경로")
    ap.add_argument("--interval", type=float, default=5.0, help="health 확인 주기(초)")
    ap.add_argument("--health-timeout", type=float, default=10.0, help="health 요청 시간 상한(초)")
    ap.add_argument("--fails", type=int, default=3, help="health 연속 실패 몇 번이면 재시작")
    ap.add_argument("--startup-grace", type=float, default=180.0, help="처음 뜰 때 health 실패를 봐주는 시간(초)")
    ap.add_argument("--max-restarts", type=int, default=100, help="재시작 상한(0=무한)")
    ap.add_argument("--log-file", default=None)
    ap.add_argument("--no-public", action="store_true", help="NEUMANN_PUBLIC=1을 넘기지 않는다")
    ap.add_argument("--run-for", type=float, default=0.0, help="시험용: N초 뒤 멈춘다")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    if IS_WIN:
        signal.signal(signal.SIGBREAK, _raise_kbi)
    signal.signal(signal.SIGTERM, _raise_kbi)
    return Supervisor(args).run()


if __name__ == "__main__":
    sys.exit(main())
