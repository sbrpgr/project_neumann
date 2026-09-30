"""데모 계획서(AI4S 예시 3건 + 범위 밖 1건)의 사전 계산본(오프라인 폴백)을 만든다.

    python scripts/precompute_demo.py                      파이프라인이 있으면 실행, 없으면 fixture로 대체(표시)
    python scripts/precompute_demo.py --source pipeline    파이프라인 필수(없거나 실패하면 exit 1)
    python scripts/precompute_demo.py --source fixture     fixture 강제(네트워크·API 호출 없음)
    python scripts/precompute_demo.py --out DIR            출력 폴더(기본 <NEUMANN_DATA_DIR>/precomputed)
    python scripts/precompute_demo.py --allow-empty        파이프라인 결과가 카드 0장이어도 exit 0
    python scripts/precompute_demo.py --from-results DIR   (E6-L3d) 라이브 E2E 결과(PremortemResult JSON)를 가져온다.
        새 분석을 돌리지 않는다(파이프라인·LLM import 없음). --run-commit SHA(서버 실행 커밋), --server-port 8020,
        --allow-partial(일부 계획서 결과가 없어도 있는 것만 쓴다). 자세한 규칙은 아래 "라이브 결과 가져오기".

데모 계획서(DEMO_PLANS, 대표 지시로 AI4S 3건 + 범위 밖 1건. 옛 fMRI·의료영상 예시는 뺐다):
  plan.md(전해액 GNN) · protein_ligand_affinity.md · neural_operator_weather.md(catalog.json 예시와 같다) ·
  negative_recipe.md(범위 밖: 카드 0장이 정상이다)

exit 1: 분석 실패, 재생 실패, 또는 파이프라인 결과 중 데모 계획서 카드 0장(데모 폴백으로 못 쓴다 — 항목 warnings에도 남는다).

분석: `neumann.pipeline.run_premortem(plan_text, *, session_id=...) -> PremortemResult`(E3).
  provider는 파이프라인이 설정(NEUMANN_LLM_PROVIDER)대로 고른다. 이 스크립트는 LLM을 직접 부르지 않는다.
대체: 파이프라인이 없으면(auto) `tests/fixtures/premortem_result.json`으로 대체하고, 결과의 stages(degraded)·
  notices와 매니페스트 `source="fixture"`에 표시한다. fixture가 없는 계획서는 카드 없이 사유만 저장한다.

산출(공유 데이터 폴더, gitignore — 커밋하지 않는다)
  <out>/<plan_id>.json   PremortemResult JSON. 데모 계획서(저장소의 공개 fixture)만 본문 포함, 그 밖은 본문 제외
  <out>/manifest.json    항목별 sha256·바이트·생성 시각·생성 방식별 카드 수·소요 시간·출처(pipeline|fixture)
끝나면 저장한 파일을 라우터와 같은 코드(load_precomputed)로 다시 읽어 재생되는지 확인한다.

라이브 결과 가져오기(--from-results, E6-L3d)
  - 폴더(또는 파일) 안 *.json을 읽어 PremortemResult 모양(plan_id·session_id)을 찾는다. 결과를 감싼 요약 JSON도
    안쪽까지 찾는다. 데모 계획서와는 plan_id(본문 sha256)로만 짝짓는다(파일 이름을 믿지 않는다). 같은 계획서가
    여러 번 있으면 generated_at이 가장 늦은 것을 쓰고 후보 수를 남긴다.
  - 결과는 고치지 않는다: manifest.llm_provider·llm_model, generated_at, 카드 generator(rule·mock 포함)를 그대로 둔다.
    매니페스트에 source "live_e2e", 서버 포트(8020), 서버 실행 커밋(--run-commit 또는 결과에 적힌 값, 없으면 미기록),
    가져온 쪽 커밋, 결과 파일 sha256을 적는다. 항목 generated_at은 라이브 생성 시각이다(라우터 라벨이 이 시각을 쓴다).
  - 받지 않는 것: 샘플 응답(sample), 계약 위반, astra 모델(대표 지시), 가리지 않은 이메일·ORCID·OpenReview 프로필 id·
    신원 키. 사유만 남기고(값은 출력하지 않는다) 그 후보를 버린다.
  - 기본은 전부 아니면 쓰지 않음: 데모 계획서 하나라도 결과가 없으면 아무것도 쓰지 않고 exit 1(--allow-partial 제외).
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
import re  # noqa: E402
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
EXAMPLES_DIR = ROOT / "src" / "neumann" / "api" / "templates" / "examples"
PUBLIC_PLAN_DIRS = (PLANS_DIR, EXAMPLES_DIR)  # 저장소에 공개된 예시 계획서 폴더(본문을 사전 계산본에 넣어도 된다)
FIXTURE_RESULT = ROOT / "tests" / "fixtures" / "premortem_result.json"
# 저장소 루트 기준 경로. AI4S 3건은 화면 예시 목록(catalog.json examples)과 같은 순서, 마지막은 범위 밖 입력.
DEMO_PLANS: tuple[str, ...] = (
    "tests/fixtures/plans/plan.md",
    "src/neumann/api/templates/examples/protein_ligand_affinity.md",
    "src/neumann/api/templates/examples/neural_operator_weather.md",
    "tests/fixtures/plans/negative_recipe.md",
)
OUT_OF_SCOPE_PLANS = frozenset({"tests/fixtures/plans/negative_recipe.md"})
RETIRED_DEMO_PLANS = ("plan_elife_neuro.md", "plan_medimaging.md")  # 대표 지시로 뺀 옛 fMRI·의료영상 예시
PIPELINE_IMPL = "neumann.pipeline:run_premortem"
FIXTURE_IMPL = "fallback:fixture"
LIVE_IMPL = "import:live_e2e"
LIVE_SOURCE = "live_e2e"
LIVE_TASK = "E5-L1e2e"
DEFAULT_SERVER_PORT = 8020

Runner = Callable[..., Any]


@dataclass(frozen=True)
class PlanSpec:
    demo: str  # 데모 이름(파일 이름에서 확장자 뺀 것). 단건 조회 키로도 쓴다
    path: Path
    role: str = "demo"  # demo | out_of_scope(범위 밖 입력: 카드 0장이 정상)

    @property
    def public_fixture(self) -> bool:
        """저장소의 공개 예시 계획서인가. 이것만 사전 계산본에 본문을 넣는다."""
        try:
            parent = self.path.resolve().parent
            return any(parent == d.resolve() for d in PUBLIC_PLAN_DIRS)
        except OSError:
            return False


def demo_specs() -> list[PlanSpec]:
    return [
        PlanSpec(demo=Path(rel).stem, path=ROOT / rel, role="out_of_scope" if rel in OUT_OF_SCOPE_PLANS else "demo")
        for rel in DEMO_PLANS
    ]


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


def llm_settings() -> dict[str, Any] | None:
    """설정이 요청한 provider·모델과 실제 호출 허용 여부(비밀값 아님). 실제로 쓴 값은 항목별 `llm_actual`. 못 읽으면 None."""
    try:
        from neumann.config import get_settings, live_llm_allowed

        s = get_settings()
        return {"provider_requested": s.llm_provider, "model_requested": s.llm_model, "live_llm_ok": live_llm_allowed()}
    except Exception:  # noqa: BLE001
        return None


def llm_actual(result: PremortemResult) -> dict[str, Any]:
    """결과 manifest에 적힌, 파이프라인이 실제로 쓴 provider·모델(SEC-3 강등이면 mock)."""
    man = getattr(result, "manifest", None) or {}
    if not isinstance(man, dict):
        man = getattr(man, "model_dump", lambda: {})()
    return {"provider": man.get("llm_provider"), "model": man.get("llm_model")}


def entry_warnings(result: PremortemResult, role: str = "demo") -> list[str]:
    """데모 폴백으로 쓰기 어려운 결과를 드러낸다(숨기지 않는다). 카드 0장, 건너뛴 단계, 범위 밖인데 카드가 나온 것."""
    warnings = []
    if not result.risk_cards:
        reason = result.risk_synthesis.get("no_card_reason") if isinstance(result.risk_synthesis, dict) else None
        warnings.append(f"카드 0장: {reason or '사유 없음'}")
    elif role == "out_of_scope":
        warnings.append(f"범위 밖 입력인데 카드 {len(result.risk_cards)}장")
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
            "role": spec.role,
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
            "llm_actual": llm_actual(result),
            "degraded_stages": [s.stage for s in result.stages if s.state in ("degraded", "error")],
            "plan_text_included": with_plan,
            "warnings": entry_warnings(result, spec.role),
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


# ── 라이브 결과 가져오기(E6-L3d) ──────────────────────────────────────────

MAX_RESULT_FILES = 400
MAX_RESULT_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 6
COMMIT_KEYS = ("run_commit", "server_commit", "git_commit", "commit")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
MODEL_KEYS = frozenset({"model", "llm_model", "model_id", "impl"})
# 신원 키(models.IDENTITY_TOKENS 기준, 단계 JSON 키 "name"과 "author_response" 같은 출처 종류는 뺀다).
# 결과의 자유 형식 칸에 이 이름의 키가 있으면 받지 않는다(키 이름 전체 또는 _로 나뉜 조각이 일치할 때).
IDENTITY_KEY_TOKENS = frozenset({"email", "emails", "e_mail", "orcid", "author", "authors", "reviewer", "reviewer_id",
                                 "reviewers", "affiliation", "affiliations", "institution", "signature", "signatures",
                                 "handle", "profile", "phone"})
IDENTITY_KEY_ALLOW = frozenset({"author_response", "author_responses"})
IDENTITY_KEY_PARTS = frozenset({"email", "emails", "orcid", "signature", "signatures", "affiliation", "affiliations",
                                "institution", "phone"})
OPENREVIEW_PROFILE_RE = re.compile(r"~[A-Z][A-Za-z\-]+(?:_[A-Z][A-Za-z\-]+)+\d+")


@dataclass
class Candidate:
    data: dict[str, Any]
    file: str  # 결과 폴더 기준 상대 경로(로컬 절대 경로는 남기지 않는다)
    file_sha256: str
    pointer: str  # 파일 안 위치(JSON pointer 비슷한 표기)
    commit: str | None = None  # 감싼 JSON이나 결과 manifest에 적힌 서버 실행 커밋


def _commit_in(d: dict[str, Any]) -> str | None:
    for k in COMMIT_KEYS:
        v = d.get(k)
        if isinstance(v, str) and COMMIT_RE.match(v.strip().lower()):
            return v.strip().lower()
    return None


def _walk_candidates(obj: Any, pointer: str, depth: int, commit: str | None, out: list[tuple[dict, str, str | None]]) -> None:
    if depth > MAX_DEPTH:
        return
    if isinstance(obj, dict):
        commit = _commit_in(obj) or commit
        if isinstance(obj.get("plan_id"), str) and isinstance(obj.get("session_id"), str):
            man = obj.get("manifest") if isinstance(obj.get("manifest"), dict) else {}
            out.append((obj, pointer or "/", _commit_in(man) or commit))
            return
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                _walk_candidates(v, f"{pointer}/{k}", depth + 1, commit, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                _walk_candidates(v, f"{pointer}/{i}", depth + 1, commit, out)


def collect_candidates(path: Path) -> tuple[list[Candidate], list[str]]:
    """결과 폴더(또는 파일)에서 PremortemResult 모양 후보를 모은다. (후보, 읽기 문제)."""
    problems: list[str] = []
    if path.is_file():
        base, files = path.parent, [path]
    elif path.is_dir():
        base, files = path, sorted(p for p in path.rglob("*.json") if p.is_file())
    else:
        return [], ["결과 경로가 없다"]
    if len(files) > MAX_RESULT_FILES:
        problems.append(f"JSON 파일 {len(files)}개 중 앞 {MAX_RESULT_FILES}개만 읽었다")
        files = files[:MAX_RESULT_FILES]
    found: list[Candidate] = []
    for f in files:
        name = f.relative_to(base).as_posix()
        try:
            raw = f.read_bytes()
        except OSError as exc:
            problems.append(f"{name}: 읽기 실패({type(exc).__name__})")
            continue
        if len(raw) > MAX_RESULT_BYTES:
            problems.append(f"{name}: 너무 크다({len(raw)} 바이트)")
            continue
        try:
            obj = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            problems.append(f"{name}: JSON 아님")
            continue
        hits: list[tuple[dict, str, str | None]] = []
        _walk_candidates(obj, "", 0, None, hits)
        sha = sha256_bytes(raw)
        found += [Candidate(data=d, file=name, file_sha256=sha, pointer=ptr, commit=c) for d, ptr, c in hits]
    return found, problems


def _iter_strings(obj: Any, pointer: str = "") -> Any:
    if isinstance(obj, str):
        yield pointer or "/", None, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{pointer}/{k}", str(k), None
            yield from _iter_strings(v, f"{pointer}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_strings(v, f"{pointer}/{i}")


def privacy_problems(data: dict[str, Any]) -> list[str]:
    """가리지 않은 개인정보 위치(값은 넣지 않는다): 이메일·ORCID, OpenReview 프로필 id(~Name_Name1), 신원 키."""
    from neumann.models import contains_pii

    hits: list[str] = []
    for ptr, key, text in _iter_strings(data):
        if key is not None:
            low = key.lower().replace("-", "_")
            if low not in IDENTITY_KEY_ALLOW and (low in IDENTITY_KEY_TOKENS or
                                                  any(t in IDENTITY_KEY_PARTS for t in low.split("_"))):
                hits.append(f"신원 키 {ptr}")
        elif contains_pii(text):
            hits.append(f"이메일·ORCID {ptr}")
        elif "~" in text and OPENREVIEW_PROFILE_RE.search(text):
            hits.append(f"OpenReview 프로필 id {ptr}")
    return hits


def astra_models(data: dict[str, Any]) -> list[str]:
    """astra가 들어간 모델 표기 위치(대표 지시: astra 결과는 쓰지 않는다). generator 값 "astra"는 계약 이름이라 보지 않는다."""
    out: list[str] = []

    def walk(obj: Any, ptr: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in MODEL_KEYS and isinstance(v, str) and "astra" in v.lower():
                    out.append(f"{ptr}/{k}")
                elif isinstance(v, (dict, list)):
                    walk(v, f"{ptr}/{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{ptr}/{i}")

    walk(data, "")
    return out


def vet_candidate(data: dict[str, Any]) -> tuple[PremortemResult | None, list[str], list[str]]:
    """(결과 또는 None, 거절 사유, 경고). 결과 내용은 바꾸지 않는다(모르는 최상위 키만 빼고 경고로 남긴다)."""
    reasons: list[str] = []
    if data.get("sample") is True or any(
        isinstance(s, dict) and str(s.get("impl") or "").startswith("fallback:sample") for s in data.get("stages") or []
    ):
        reasons.append("샘플 응답(파이프라인 미연결 — 분석 결과 아님)")
    astra = astra_models(data)
    if astra:
        reasons.append(f"astra 모델 표기 {len(astra)}곳(대표 지시로 쓰지 않는다): {', '.join(astra[:3])}")
    pii = privacy_problems(data)
    if pii:
        reasons.append(f"가리지 않은 개인정보 {len(pii)}곳: {', '.join(pii[:3])}")
    known = set(PremortemResult.model_fields)
    extra = sorted(k for k in data if k not in known)
    warnings = [f"결과 밖 최상위 키는 빼고 저장: {', '.join(extra)}"] if extra else []
    try:
        result = PremortemResult.model_validate({k: v for k, v in data.items() if k in known})
    except Exception as exc:  # noqa: BLE001 — 값은 남기지 않고 위치만
        errs = getattr(exc, "errors", lambda: [])()
        where = ", ".join("/".join(str(x) for x in e.get("loc", ())) for e in errs[:3]) if errs else ""
        reasons.append(f"결과 계약 위반({type(exc).__name__}{': ' + where if where else ''})")
        return None, reasons, warnings
    if reasons:
        return None, reasons, warnings
    return result, [], warnings


def generation_label(result: PremortemResult) -> str:
    """생성 방식 한 줄(숨기지 않는다): provider·모델, 규칙 대체 카드 수, mock."""
    act = llm_actual(result)
    provider, model = act.get("provider") or "미기록", act.get("model") or "미기록"
    by_gen = cards_by_generator(result)
    parts = [f"{provider}:{model}"]
    if by_gen.get("rule"):
        parts.append(f"규칙 대체 카드 {by_gen['rule']}장(비상 경로)")
    if by_gen.get("mock") or provider == "mock":
        parts.append("mock(가짜 LLM)")
    if result.status != "ok":
        parts.append(f"status {result.status}")
    return " · ".join(parts)


def _git_head() -> str | None:
    try:
        import subprocess

        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, ValueError):
        return None
    head = out.stdout.strip()
    return head if out.returncode == 0 and COMMIT_RE.match(head) else None


def import_live(
    specs: list[PlanSpec],
    results: Path,
    out_dir: Path,
    *,
    run_commit: str | None = None,
    server_port: int = DEFAULT_SERVER_PORT,
    allow_partial: bool = False,
    log: Callable[[str], None] = print,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """라이브 E2E 결과를 사전 계산본으로 옮긴다. 새 분석을 돌리지 않는다. (매니페스트, 실패 목록).

    실패가 있고 allow_partial이 아니면 아무것도 쓰지 않고 ({}, 실패)를 돌려준다.
    """
    t_all = time.perf_counter()
    candidates, read_problems = collect_candidates(results)
    for p in read_problems:
        log(f"  읽기: {p}")
    log(f"결과: {results.name} · 후보 {len(candidates)}건")
    by_plan: dict[str, list[Candidate]] = {}
    for c in candidates:
        by_plan.setdefault(str(c.data.get("plan_id")), []).append(c)

    picked: list[tuple[PlanSpec, str, PremortemResult, Candidate, list[str], int, list[str]]] = []
    failures: list[dict[str, str]] = []
    for spec in specs:
        try:
            plan_text = spec.path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append({"demo": spec.demo, "error": f"계획서를 읽을 수 없다({type(exc).__name__})"})
            continue
        plan_id = PlanDocument.from_text(plan_text, session_id="live-import").plan_id
        pool = by_plan.get(plan_id, [])
        good: list[tuple[PremortemResult, Candidate, list[str]]] = []
        rejected: list[str] = []
        for c in pool:
            result, reasons, warns = vet_candidate(c.data)
            if result is None:
                rejected.append(f"{c.file}{c.pointer if c.pointer != '/' else ''}: {'; '.join(reasons)}")
            else:
                good.append((result, c, warns))
        for r in rejected:
            log(f"  {spec.demo}: 거절 {r}")
        if not good:
            why = f"라이브 결과 없음(plan_id 일치 후보 {len(pool)}건" + (f", 거절 {len(rejected)}건: {rejected[0]}" if rejected else "") + ")"
            failures.append({"demo": spec.demo, "error": why})
            continue
        good.sort(key=lambda g: g[0].generated_at)
        result, cand, warns = good[-1]
        picked.append((spec, plan_text, result, cand, warns, len(good), rejected))

    if failures and not allow_partial:
        return {}, failures

    commits = {c.commit for _, _, _, c, *_ in picked if c.commit}
    if run_commit:
        commit, commit_src = run_commit.strip().lower(), "인자(--run-commit)"
    elif len(commits) == 1:
        commit, commit_src = commits.pop(), "결과 파일"
    else:
        commit, commit_src = None, ("결과마다 다름: " + ", ".join(sorted(commits))) if commits else "미기록"

    out_dir.mkdir(parents=True, exist_ok=True)
    imported_at = iso(utc_now())
    entries: list[dict[str, Any]] = []
    for spec, plan_text, result, cand, warns, n_good, rejected in picked:
        name = f"{result.plan_id}.json"
        if not RESULT_FILE_RE.match(name):
            failures.append({"demo": spec.demo, "error": "plan_id가 파일 이름으로 쓸 수 없는 형식"})
            continue
        data, with_plan = serialize(result, spec)
        _write_atomic(out_dir / name, data)
        by_gen = cards_by_generator(result)
        man = result.manifest if isinstance(result.manifest, dict) else {}
        warnings = entry_warnings(result, spec.role) + warns
        if not llm_actual(result).get("model"):
            warnings.append("결과 manifest에 llm_model 없음(모델 미기록)")
        if n_good > 1:
            warnings.append(f"같은 계획서 결과 {n_good}건 중 generated_at이 가장 늦은 것")
        entry = {
            "plan_id": result.plan_id,
            "demo": spec.demo,
            "role": spec.role,
            "title": plan_title(plan_text) if spec.public_fixture else None,
            "plan_file": rel(spec.path),
            "file": name,
            "sha256": sha256_bytes(data),
            "bytes": len(data),
            "generated_at": iso(result.generated_at),  # 라이브 생성 시각(라우터 라벨이 쓴다)
            "result_generated_at": iso(result.generated_at),
            "imported_at": imported_at,
            "elapsed_s": man.get("total_s"),
            "source": LIVE_SOURCE,
            "impl": LIVE_IMPL,
            "status": result.status,
            "cards_total": len(result.risk_cards),
            "cards_by_generator": by_gen,
            "models": result_models(result),
            "llm_actual": llm_actual(result),
            "generation": generation_label(result),
            "degraded_stages": [s.stage for s in result.stages if s.state in ("degraded", "error")],
            "plan_text_included": with_plan,
            "live": {
                "task": LIVE_TASK,
                "server_port": server_port,
                "results_file": cand.file,
                "results_pointer": cand.pointer,
                "results_file_sha256": cand.file_sha256,
                "candidates": n_good,
                "rejected": rejected,
            },
            "warnings": warnings,
        }
        entries.append(entry)
        gen = ", ".join(f"{k} {v}" for k, v in by_gen.items() if v)
        log(f"  {spec.demo}: {LIVE_SOURCE} · {entry['generation']} · 생성 {entry['generated_at']} · "
            f"카드 {len(result.risk_cards)}" + (f"({gen})" if gen else "") + f" · {name}")

    providers = sorted({str(e["llm_actual"].get("provider")) for e in entries if e["llm_actual"].get("provider")})
    models = sorted({str(e["llm_actual"].get("model")) for e in entries if e["llm_actual"].get("model")})
    times = sorted(e["generated_at"] for e in entries)
    manifest = {
        "kind": MANIFEST_KIND,
        "version": MANIFEST_VERSION,
        "generated_at": imported_at,
        "generator": "scripts/precompute_demo.py --from-results",
        "source": LIVE_SOURCE if entries else "none",
        "live_run": {
            "task": LIVE_TASK,
            "server_port": server_port,
            "server_label": f"라이브 서버({server_port})",
            "run_commit": commit,
            "run_commit_source": commit_src,
            "import_commit": _git_head(),
            "results": results.name,
            "result_generated_at": [times[0], times[-1]] if times else [],
            "providers": providers,
            "models": models,
            "partial": bool(failures),
        },
        "pipeline": {"available": False, "impl": LIVE_IMPL, "note": "라이브 E2E 결과 가져오기 — 새 분석 없음"},
        "llm": {"source": "results", "providers": providers, "models": models},
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
    parser.add_argument("--from-results", type=Path, default=None, metavar="DIR",
                        help="라이브 E2E 결과(PremortemResult JSON) 폴더·파일을 가져온다(새 분석 없음)")
    parser.add_argument("--run-commit", default=None, help="라이브 서버가 돈 커밋(결과에 없으면 이 값을 적는다)")
    parser.add_argument("--server-port", type=int, default=DEFAULT_SERVER_PORT, help="라이브 서버 포트 표기(기본 8020)")
    parser.add_argument("--allow-partial", action="store_true", help="가져오기: 결과가 없는 계획서가 있어도 있는 것만 쓴다")
    args = parser.parse_args(argv)

    specs = [PlanSpec(demo=p.stem, path=p) for p in args.plan] if args.plan else demo_specs()
    out_dir = args.out if args.out is not None else default_out_dir()
    print(f"출력: {out_dir}")
    if args.run_commit is not None and not COMMIT_RE.match(args.run_commit.strip().lower()):
        print("실패: --run-commit은 16진수 커밋 해시(7~40자)")
        return 2
    if args.from_results is not None:
        manifest, failures = import_live(specs, args.from_results, out_dir, run_commit=args.run_commit,
                                         server_port=args.server_port, allow_partial=args.allow_partial)
    else:
        manifest, failures = build(specs, out_dir, source=args.source)
    if not manifest:
        for f in failures:
            print(f"실패 {f['demo']}: {f['error']}")
        if args.from_results is not None:
            print("가져오기 중단: 아무것도 쓰지 않았다(--allow-partial로 있는 것만 쓸 수 있다)")
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
    live = manifest.get("live_run")
    if live:
        print(f"라이브: {live['server_label']} · 모델 {', '.join(live['models']) or '미기록'} · "
              f"서버 커밋 {live['run_commit'] or '미기록'}({live['run_commit_source']}) · 가져온 커밋 {live['import_commit'] or '미기록'}")
    empty = [e["demo"] for e in manifest["entries"]
             if e["source"] in ("pipeline", LIVE_SOURCE) and e["cards_total"] == 0 and e.get("role") != "out_of_scope"]
    if empty and not args.allow_empty:
        print(f"  파이프라인 결과 카드 0장: {', '.join(empty)} — 데모 폴백으로 못 쓴다(--allow-empty로 무시)")
    partial_ok = args.from_results is not None and args.allow_partial  # 빠진 계획서는 위에 "실패"로 출력했다
    return 1 if ((failures and not partial_ok) or problems or n == 0 or (empty and not args.allow_empty)) else 0


if __name__ == "__main__":
    sys.exit(main())
