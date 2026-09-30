"""Reproducible WARMUP measurements and headless UI probe, mock LLM only.

python tests/e4/warmup_probe.py --model PATH --index PATH --out OUTSIDE_REPO.json
python tests/e4/warmup_probe.py --ui --out OUTSIDE_REPO_DIR
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]


def create_app():
    # Do this before importing API modules: neither settings loader reads .env.
    from neumann.config import Settings, get_settings
    from neumann.index.settings import IndexSettings, get_index_settings

    Settings.model_config["env_file"] = None
    IndexSettings.model_config["env_file"] = None
    get_settings.cache_clear()
    get_index_settings.cache_clear()
    from neumann.api import main

    @main.app.get("/__warmup_probe_ready", include_in_schema=False)
    def probe_ready():
        return {"pid": os.getpid(), "parent_pid": os.getppid()}

    return main.app


def create_ui_app():
    create_app()  # disable .env loading before constructing the probe
    from neumann.api import main, serving, jobs, warmup
    from scripts.serve_fake_app import integrate, fake_result

    release = threading.Event()

    def gated():
        if not release.wait(180):
            raise RuntimeError("UI probe did not release warmup")
        return {"backend": "hybrid", "n_works": 1}

    warmup.warm_search = gated
    srv = serving.Serving(serving.ServingConfig(warmup=True, cache_enabled=False))
    app = integrate(srv, fake_result)
    jobs.install(app, load_pipeline=main._load_pipeline,
                 config=jobs.JobsConfig(rate_per_min=0, per_ip=0))

    @app.post("/__warmup_release")
    def release_warmup():
        release.set()
        return {"released": True}

    return app


def free_port():
    # Prefer the upper range to reduce collisions with other workers' 81xx probes.
    for port in list(range(8190, 8200)) + list(range(8100, 8190)):
        if port == 8171:
            continue
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free 81xx port")


def start_server(args, enabled, ui=False):
    env = os.environ.copy()
    for name in ("OPENAI_API_KEY", "NEUMANN_PSEUDONYM_SALT", "NEUMANN_LIVE_LLM_OK", "NEUMANN_LIVE_TESTS"):
        env.pop(name, None)
    env.update(NEUMANN_LLM_PROVIDER="mock", NEUMANN_WARMUP=str(int(enabled)),
               PYTHONPATH="src;.", NEUMANN_PUBLIC="0", NEUMANN_RESULT_CACHE="0",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               NEUMANN_DATA_DIR=str(args.out.parent / "probe_data"))
    if not ui:
        env.update(NEUMANN_EMBED_MODEL=args.model, NEUMANN_INDEX_DIR=args.index)
    port = free_port()
    t0 = time.monotonic()
    factory = "tests.e4.warmup_probe:create_ui_app" if ui else "tests.e4.warmup_probe:create_app"
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", factory,
                                "--factory", "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
                               cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return process, f"http://127.0.0.1:{port}", t0


def wait_health(client, process, deadline):
    last_status = "no_response"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("probe server exited")
        try:
            ready = client.get("/__warmup_probe_ready")
            if ready.status_code != 200 or process.pid not in (
                ready.json().get("pid"), ready.json().get("parent_pid")
            ):
                raise RuntimeError("response belongs to a different server")
            response = client.get("/health")
            last_status = str(response.status_code)
            if response.status_code == 200:
                return response.json()
        except Exception as exc:
            last_status = type(exc).__name__
        time.sleep(0.2)
    raise TimeoutError("server did not become ready: " + last_status)


def stop_server(process):
    # Only this probe's child PID is stopped; never touch any shared server.
    if process.poll() is None:
        if os.name == "nt":
            # A Windows venv launcher has a separate interpreter child PID.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=20)


def measure(args, enabled):
    import httpx

    process, url, t0 = start_server(args, enabled)
    try:
        with httpx.Client(base_url=url, timeout=30, trust_env=False) as client:
            health = wait_health(client, process, t0 + 600)
            startup = time.monotonic() - t0
            observed = [health["warmup"]["state"]]
            if enabled:
                while health["warmup"]["state"] in ("pending", "running"):
                    if time.monotonic() - t0 > 900:
                        raise TimeoutError("warmup did not complete")
                    time.sleep(0.5)
                    health = client.get("/health").json()
                    if health["warmup"]["state"] != observed[-1]:
                        observed.append(health["warmup"]["state"])
                if health["warmup"]["state"] != "done":
                    raise RuntimeError("warmup failed: " + health["warmup"].get("error_kind", "unknown"))
            ready = time.monotonic() - t0
            plan = (ROOT / "tests/fixtures/plans/plan.md").read_text(encoding="utf-8")
            a0 = time.monotonic()
            response = client.post("/premortem/jobs", json={"plan_text": plan, "format": "result"})
            if response.status_code != 202:
                raise RuntimeError("job admission failed")
            jid = response.json()["job_id"]
            while True:
                status = client.get(f"/premortem/jobs/{jid}").json()
                if status.get("status") in ("done", "error"):
                    break
                if time.monotonic() - a0 > 900:
                    raise TimeoutError("analysis did not complete")
                time.sleep(0.2)
            if status["status"] != "done":
                raise RuntimeError("analysis job failed")
            result = status["result"]
            row = {"warmup_enabled": enabled, "port": int(url.rsplit(":", 1)[1]),
                   "startup_health_s": round(startup, 3), "startup_ready_s": round(ready, 3),
                   "warmup": health["warmup"], "warmup_observed_states": observed,
                   "first_analysis_s": round(time.monotonic() - a0, 3),
                   "startup_to_first_result_s": round(time.monotonic() - t0, 3),
                   "result_status": result.get("status"), "cards": len(result.get("risk_cards", [])),
                   "timings_s": result.get("manifest", {}).get("timings_s", {}),
                   "search_stage": [{"status": s.get("status"), "elapsed_s": s.get("elapsed_s")}
                                    for s in result.get("stages", []) if s.get("name") == "search"]}
            print(json.dumps(row, ensure_ascii=True), flush=True)
            return row
    finally:
        stop_server(process)


def ui_probe(args):
    import httpx
    from playwright.sync_api import sync_playwright

    process, url, t0 = start_server(args, True, ui=True)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(base_url=url, timeout=30, trust_env=False) as client:
            wait_health(client, process, t0 + 120)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            rows = []
            try:
                for width in (1440, 390):
                    page = browser.new_page(viewport={"width": width, "height": 960})
                    page.goto(url)
                    # Exercise the actual UI polling path; no desktop browser access.
                    page.locator('[data-mode="text"]').click()
                    page.locator("textarea").first.fill((ROOT / "tests/fixtures/plans/plan.md").read_text(encoding="utf-8"))
                    page.locator("#btnStart").click()
                    page.get_by_text("모델 준비 중", exact=False).first.wait_for(timeout=30000)
                    page.screenshot(path=str(args.out / f"warmup-{width}.png"), full_page=True)
                    rows.append({"width": width, "warmup_visible": True,
                                 "overflow_px": page.evaluate("Math.max(0,document.documentElement.scrollWidth-innerWidth)")})
                    page.close()
            finally:
                browser.close()
                with httpx.Client(base_url=url, trust_env=False) as client:
                    client.post("/__warmup_release")
            print(json.dumps(rows), flush=True)
            (args.out / "ui-result.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    finally:
        stop_server(process)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--index")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ui", action="store_true")
    args = parser.parse_args()
    if args.ui:
        ui_probe(args)
    else:
        if not args.model or not args.index:
            parser.error("--model and --index are required for local measurements")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for enabled in (False, True):
            rows.append(measure(args, enabled))
            args.out.write_text(json.dumps(rows, indent=2, ensure_ascii=True), encoding="utf-8")
