"""데모 계획서 3건의 사전 계산본(오프라인 폴백)을 만든다.

    python scripts/precompute_demo.py                      파이프라인이 있으면 실행, 없으면 fixture로 대체(표시)
    python scripts/precompute_demo.py --source pipeline    파이프라인 필수(없거나 실패하면 exit 1)
    python scripts/precompute_demo.py --source fixture     fixture 강제(네트워크·API 호출 없음)
    python scripts/precompute_demo.py --out DIR            출력 폴더(기본 <NEUMANN_DATA_DIR>/precomputed)
    python scripts/precompute_demo.py --allow-empty        파이프라인 결과가 카드 0장이어도 exit 0

exit 1: 분석 실패, 재생 실패, 또는 파이프라인 결과 중 카드 0장(데모 폴백으로 못 쓴다 — 항목 warnings에도 남는다).

분석: `neumann.pipeline.run_premortem(plan_text, *, session_id=...) -> PremortemResult`(E3).
  provider는 파이프라인이 설정(NEUMANN_LLM_PROVIDER)대로 고른다. 이 스크립트는 LLM을 직접 부르지 않는다.
대체: 파이프라인이 없으면(auto) `tests/fixtures/premortem_result.json`으로 대체하고, 결과의 stages(degraded)·
  notices와 매니페스트 `source="fixture"`에 표시한다. fixture가 없는 계획서는 카드 없이 사유만 저장한다.

산출(공유 데이터 폴더, gitignore — 커밋하지 않는다)
  <out>/<plan_id>.json   PremortemResult JSON. 데모 계획서(저장소의 공개 fixture)만 본문 포함, 그 밖은 본문 제외
  <out>/manifest.json    항목별 sha256·바이트·생성 시각·생성 방식별 카드 수·소요 시간·출처(pipeline|fixture)
끝나면 저장한 파일을 라우터와 같은 코드(load_precomputed)로 다시 읽어 재생되는지 확인한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":  # 직접 실행할 때 src·루트를 경로에 넣는다(PYTHONPATH가 없어도 돌게)
    for _p in (str(ROOT), str(ROOT / "src")):
        if _p not in sys.path:
            sys.path.insert(0, _p)

import argparse  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from collections.abc import Callable  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from typing import Any  # noqa: E402

from neumann.api.precomputed import (  # noqa: E402
    MANIFEST_KIND,
    MANIFEST_NAME,
    MANIFEST_VERSION,
    PRECOMPUTED_SUBDIR,
    RESULT_FILE_RE,
    PrecomputedError,
    encode_json,
    load_precomputed,
    sha256_bytes,
)
from neumann.models import Generator, PlanDocument, PremortemResult, StageStatus  # noqa: E402

PLANS_DIR = ROOT / "tests" / "fixtures" / "plans"
FIXTURE_RESULT = ROOT / "tests" / "fixtures" / "premortem_result.json"
DEMO_PLANS: tuple[str, ...] = ("plan.md", "plan_elife_neuro.md", "plan_medimaging.md")
PIPELINE_IMPL = "neumann.pipeline:run_premortem"
FIXTURE_IMPL = "fallback:fixture"

Runner = Callable[..., Any]


@dataclass(frozen=True)
class PlanSpec:
    demo: str  # 데모 이름(파일 이름에서 확장자 뺀 것). 단건 조회 키로도 쓴다
    path: Path

    @property
    def public_fixture(self) -> bool:
        """저장소의 공개 데모 계획서인가. 이것만 사전 계산본에 본문을 넣는다."""
        try:
            return self.path.resolve().parent == PLANS_DIR.resolve()
        except OSError:
            return False


def demo_specs() -> list[PlanSpec]:
    return [PlanSpec(demo=Path(name).stem, path=PLANS_DIR / name) for name in DEMO_PLANS]


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def default_out_dir() -> Path:
    from neumann.config import get_settings

    return Path(get_settings().data_dir) / PRECOMPUTED_SUBDIR


def load_pipeline() -> tuple[Runner | None, str]:
    """(run_premortem 또는 None, 설명). 무거운 모듈이라 여기서만 import한다."""
    try:
        module = importlib.import_module("neumann.pipeline")
    except ModuleNotFoundError as exc:
        if exc.name == "neumann.pipeline":
            return None, "neumann.pipeline 모듈 없음"
        return None, f"neumann.pipeline import 실패(ModuleNotFoundError: {exc.name})"
    except Exception as exc:  # noqa: BLE001 — import 실패도 사유로 남기고 대체로 간다
        return None, f"neumann.pipeline import 실패({type(exc).__name__})"
    runner = getattr(module, "run_premortem", None)
    if not callable(runner):
        return None, "neumann.pipeline.run_premortem 없음"
    return runner, "연결됨"


# ── 결과 만들기 ────────────────────────────────────────────────────────────


def _fixture_stage(reason: str) -> StageStatus:
    return StageStatus(
        stage="precompute_source",
        state="degraded",
        detail=f"{reason}: 실제 분석 대신 fixture 결과로 대체",
        phase="precompute",
        impl=FIXTURE_IMPL,
    )


def fixture_result(spec: PlanSpec, plan_text: str, reason: str) -> PremortemResult:
    """파이프라인 없이 만드는 대체 결과. 강등(degraded)과 대체 사실을 결과 안에 남긴다."""
    plan = PlanDocument.from_text(plan_text, session_id=f"precomputed-{spec.demo}")
    stage = _fixture_stage(reason).model_dump(mode="json")
    notice = f"[대체] 분석 파이프라인 미연결({reason}) — 실제 분석이 아니라 fixture 결과다"
    fixture = json.loads(FIXTURE_RESULT.read_text(encoding="utf-8")) if FIXTURE_RESULT.is_file() else None
    if fixture is not None and fixture.get("plan_id") == plan.plan_id:
        fixture["stages"] = [*fixture.get("stages", []), stage]
        fixture["notices"] = [notice, *fixture.get("notices", [])]
        return PremortemResult.model_validate(fixture)
    no_card = "이 계획서의 fixture 결과가 없어 카드 없이 저장했다(파이프라인 연결 뒤 다시 만든다)"
    return PremortemResult.model_validate(
        {
            "session_id": plan.session_id,
            "plan_id": plan.plan_id,
            "plan": plan.model_dump(mode="json"),
            "status": "degraded",
            "stages": [stage],
            "notices": [notice, no_card],
            "risk_synthesis": {"no_card_reason": no_card},
        }
    )


def _as_result(value: Any) -> PremortemResult:
    if isinstance(value, PremortemResult):
        return value
    if isinstance(value, dict):
        return PremortemResult.model_validate(value)
    raise TypeError(f"run_premortem이 PremortemResult가 아닌 {type(value).__name__}를 돌려줬다")


def cards_by_generator(result: PremortemResult) -> dict[str, int]:
    counts = {g.value: 0 for g in Generator}
    for card in result.risk_cards:
        counts[card.generator.value] = counts.get(card.generator.value, 0) + 1
    return counts


def result_models(result: PremortemResult) -> list[str]:
    """결과를 만든 LLM 모델 id(카드의 model, 단계 impl의 "provider:model"). 규칙·fixture는 넣지 않는다."""
    models = {c.model for c in result.risk_cards if c.model}
    for stage in result.stages:
        impl = stage.impl or ""
        provider, _, model = impl.partition(":")
        if provider in ("openai", "mock") and model:
            models.add(impl)
    return sorted(models)


def llm_settings() -> dict[str, str] | None:
    """파이프라인이 쓸 provider·모델 이름(비밀값 아님). 설정을 못 읽으면 None."""
    try:
        from neumann.config import get_settings

        s = get_settings()
        return {"provider": s.llm_provider, "model": s.llm_model}
    except Exception:  # noqa: BLE001
        return None


def entry_warnings(result: PremortemResult) -> list[str]:
    """데모 폴백으로 쓰기 어려운 결과를 드러낸다(숨기지 않는다). 카드 0장, 건너뛴 단계."""
    warnings = []
    if not result.risk_cards:
        reason = result.risk_synthesis.get("no_card_reason") if isinstance(result.risk_synthesis, dict) else None
        warnings.append(f"카드 0장: {reason or '사유 없음'}")
    skipped = [s.stage for s in result.stages if s.state == "skipped"]
    if skipped:
        warnings.append("건너뛴 단계: " + ", ".join(skipped))
    return warnings


def plan_title(plan_text: str) -> str | None:
    for line in plan_text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:120]
    return None


def serialize(result: PremortemResult, spec: PlanSpec) -> tuple[bytes, bool]:
    """저장 바이트와 본문 포함 여부. 공개 데모 계획서가 아니면 계획서 본문(plan)을 뺀다."""
    if spec.public_fixture:
        return encode_json(result.model_dump(mode="json")), True
    return encode_json(result.model_copy(update={"plan": None}).model_dump(mode="json")), False


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


# ── 실행 ──────────────────────────────────────────────────────────────────


def build(
    specs: list[PlanSpec],
    out_dir: Path,
    *,
    source: str = "auto",
    pipeline_loader: Callable[[], tuple[Runner | None, str]] | None = None,
    log: Callable[[str], None] = print,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """계획서마다 결과를 만들어 저장하고 매니페스트를 쓴다. (매니페스트, 실패 목록)을 돌려준다."""
    if source not in ("auto", "pipeline", "fixture"):
        raise ValueError(f"source는 auto|pipeline|fixture: {source!r}")
    runner: Runner | None = None
    pipeline_note = "요청으로 fixture 사용(--source fixture)"
    if source != "fixture":
        runner, pipeline_note = (pipeline_loader or load_pipeline)()
        if runner is None and source == "pipeline":
            return {}, [{"demo": "*", "error": f"파이프라인 필수인데 없다: {pipeline_note}"}]
    log(f"분석: {PIPELINE_IMPL if runner else FIXTURE_IMPL} ({pipeline_note})")

    out_dir.mkdir(parents=True, exist_ok=True)
    t_all = time.perf_counter()
    entries: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for spec in specs:
        try:
            plan_text = spec.path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append({"demo": spec.demo, "error": f"계획서를 읽을 수 없다({type(exc).__name__})"})
            continue
        t0 = time.perf_counter()
        try:
            if runner is not None:
                result = _as_result(runner(plan_text, session_id=f"precomputed-{spec.demo}"))
                used, impl = "pipeline", PIPELINE_IMPL
            else:
                result = fixture_result(spec, plan_text, pipeline_note)
                used, impl = "fixture", FIXTURE_IMPL
        except Exception as exc:  # noqa: BLE001 — 한 건 실패로 나머지를 멈추지 않는다. 메시지는 비밀값 우려로 남기지 않는다
            failures.append({"demo": spec.demo, "error": f"분석 실패({type(exc).__name__})"})
            log(f"  {spec.demo}: 실패 {type(exc).__name__}")
            continue
        elapsed = time.perf_counter() - t0
        name = f"{result.plan_id}.json"
        if not RESULT_FILE_RE.match(name):
            failures.append({"demo": spec.demo, "error": "plan_id가 파일 이름으로 쓸 수 없는 형식"})
            continue
        data, with_plan = serialize(result, spec)
        _write_atomic(out_dir / name, data)
        by_gen = cards_by_generator(result)
        entry = {
            "plan_id": result.plan_id,
            "demo": spec.demo,
            "title": plan_title(plan_text) if spec.public_fixture else None,
            "plan_file": rel(spec.path),
            "file": name,
            "sha256": sha256_bytes(data),
            "bytes": len(data),
            "generated_at": iso(utc_now()),
            "result_generated_at": iso(result.generated_at),
            "elapsed_s": round(elapsed, 3),
            "source": used,
            "impl": impl,
            "status": result.status,
            "cards_total": len(result.risk_cards),
            "cards_by_generator": by_gen,
            "models": result_models(result),
            "degraded_stages": [s.stage for s in result.stages if s.state in ("degraded", "error")],
            "plan_text_included": with_plan,
            "warnings": entry_warnings(result),
        }
        entries.append(entry)
        gen = ", ".join(f"{k} {v}" for k, v in by_gen.items() if v)
        cards = f"카드 {len(result.risk_cards)}" + (f"({gen})" if gen else "")
        log(f"  {spec.demo}: {used} · status {result.status} · {cards} · {elapsed:.2f}s · {name}")

    sources = sorted({e["source"] for e in entries})
    manifest = {
        "kind": MANIFEST_KIND,
        "version": MANIFEST_VERSION,
        "generated_at": iso(utc_now()),
        "generator": "scripts/precompute_demo.py",
        "source": sources[0] if len(sources) == 1 else ("mixed" if sources else "none"),
        "pipeline": {"available": runner is not None, "impl": PIPELINE_IMPL if runner else FIXTURE_IMPL, "note": pipeline_note},
        "llm": llm_settings() if runner is not None else None,
        "total_elapsed_s": round(time.perf_counter() - t_all, 3),
        "entries": entries,
        "failures": failures,
    }
    _write_atomic(out_dir / MANIFEST_NAME, encode_json(manifest))
    return manifest, failures


def replay_check(out_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """라우터와 같은 코드로 다시 읽는다. 문제 목록(비었으면 재생 가능)."""
    problems = []
    for entry in manifest.get("entries", []):
        try:
            load_precomputed(entry["plan_id"], out_dir)
        except PrecomputedError as exc:
            problems.append(f"{entry.get('demo')}: {exc.code} {exc.message}")
    return problems


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=("auto", "pipeline", "fixture"), default="auto")
    parser.add_argument("--out", type=Path, default=None, help="출력 폴더(기본 <NEUMANN_DATA_DIR>/precomputed)")
    parser.add_argument("--plan", type=Path, action="append", default=None, help="계획서 경로(여러 번). 기본은 데모 3건")
    parser.add_argument(
        "--allow-empty", action="store_true", help="파이프라인 결과가 카드 0장이어도 exit 0(기본은 exit 1: 데모 폴백으로 못 쓴다)"
    )
    args = parser.parse_args(argv)

    specs = [PlanSpec(demo=p.stem, path=p) for p in args.plan] if args.plan else demo_specs()
    out_dir = args.out if args.out is not None else default_out_dir()
    print(f"출력: {out_dir}")
    manifest, failures = build(specs, out_dir, source=args.source)
    if not manifest:
        for f in failures:
            print(f"실패: {f['error']}")
        return 1
    problems = replay_check(out_dir, manifest)
    n = len(manifest["entries"])
    print(f"매니페스트: {out_dir / MANIFEST_NAME} (항목 {n}, 출처 {manifest['source']}, 전체 {manifest['total_elapsed_s']}s)")
    print(f"재생 확인: {n - len(problems)}/{n}")
    for p in problems:
        print(f"  재생 실패 {p}")
    for f in failures:
        print(f"  실패 {f['demo']}: {f['error']}")
    for e in manifest["entries"]:
        for w in e["warnings"]:
            print(f"  경고 {e['demo']}: {w}")
    empty = [e["demo"] for e in manifest["entries"] if e["source"] == "pipeline" and e["cards_total"] == 0]
    if empty and not args.allow_empty:
        print(f"  파이프라인 결과 카드 0장: {', '.join(empty)} — 데모 폴백으로 못 쓴다(--allow-empty로 무시)")
    return 1 if (failures or problems or n == 0 or (empty and not args.allow_empty)) else 0


if __name__ == "__main__":
    sys.exit(main())
