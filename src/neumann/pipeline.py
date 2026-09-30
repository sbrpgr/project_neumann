"""분석 파이프라인: 계획서 → 적합성 → 유사 연구 → astra 지적 추출 → astra 카드 합성 → 원문 대조
→ 예상 심사평 → 예방 체크리스트 → 2차 의미검증.

    run_premortem(plan_text, *, session_id=None, on_stage=None) -> PremortemResult

단계(StageStatus.stage / phase):
  plan_normalize (INPUT) → fitness (INPUT, astra, E3-L1c) → query_axes (INPUT, astra ①) → search (EVIDENCE)
  → extract_issues (EVIDENCE, astra ②) → synthesize_cards (RISK, astra ③) → verify_evidence (REVIEW)
  → expected_review (REVIEW, astra, E3-L1a) → checklist (ACTION, astra, E3-L1b) → semantic_validate (ACTION, astra, E3-L1b)

- 예외로 죽지 않는다. 단계가 실패하면 그 단계만 규칙으로 대신하거나(비상 경로) 건너뛰고 StageStatus에 남긴다.
- 강등(degraded/error)이 하나라도 있으면 결과 status가 "degraded"다(models.PremortemResult가 강제).
- 카드가 0장이면 사유를 `risk_synthesis.no_card_reason`과 `notices`에 담는다.
- 카드 근거는 모두 원문 대조(Excerpt.verify_against)를 통과한 것만 남는다.
- 적합성 판정이 "분석하지 않음"(unfit)이면 검색 전에 끝낸다(카드 0장·사유). 적합성 모듈(E3-L1c)이 없으면 그 단계는
  skipped로 남기고 astra ①의 연구계획서 판정으로 대신한다(E3-L0 동작).
- LLM 단계(적합성·예상 심사평·체크리스트·2차 검증)는 provider 어댑터(`review.provider_llm_call`)로 부른다. 생성 주체는
  provider의 `generator` 속성(openai→astra, mock→mock, off→rule)에서만 읽는다. 호출마다 시간 상한은 `llm.task_options`.
- 같은 계획서(plan_id)는 astra 검색어를 캐시(`data/cache/queries/`)해 같은 유사 연구가 나온다. 적중 여부는
  `plan_checks.queries.cache`와 `manifest.query_cache`에 싣는다.
- `manifest.timings_s`(단계별 소요), `total_s`(전체), `stage_limits_s`(LLM 단계 호출 상한).
- 카드 뒤 v1 단계는 의존 그래프(`V1_DEPENDS`)대로 스레드에서 동시에 돈다(E3-L1y): 예상 심사평 ∥ (체크리스트 → 2차 검증).
  결과·단계 기록 순서는 순차 실행과 같다(`V1_STAGES` 순서로 합친다). `manifest.v1_parallel`·`v1_wall_s`.
- 진행 보고(E3-L1y): `on_stage(stage, state, elapsed_s)` — 단계 시작에 state="running"(elapsed 0.0), 끝에
  최종 상태(ok|degraded|error|skipped)와 그 단계 소요. 콜백은 run_premortem을 부른 스레드에서만 불린다.
- 입력 분량 단계(E3-L1s, 적합성 모듈의 `input_quality`): `plan_checks.input_quality`·`manifest.input_quality`에 싣는다.
  reject(판정할 거리가 없음)는 LLM 호출 없이 거절하고 무엇을 더 적을지 안내한다. warn(짧지만 분야·방법이 보임)은
  경고를 notices에 싣고 끝까지 분석한다: 적합성 보류 + 검색어 단계의 "계획서 아님"이어도 규칙 신호가 무관한 글이 아니고
  유사 연구 검색이 강하게 맞으면(관련도 RESEARCH_GATE_MIN_TOP 이상 논문 RESEARCH_GATE_MIN_WORKS편 이상) 멈추지 않고
  "적합성 보류였으나 유사 연구 근거로 진행"을 `plan_checks.research_gate`·notices에 남긴다. 검색 점수 하한을 넘은
  논문이 없으면 하한 없이 상위 k편을 "낮은 유사도"로 쓰고, 카드가 0장이면 분야 수준 카드(규칙 합성, degraded)를 만든다.

명령줄: python -m neumann.pipeline PLAN.md [--provider openai|mock|off] [--backend index|fixture --corpus X.json]
"""

from __future__ import annotations

import argparse
import contextvars
import inspect
import json
import logging
import re
import sys
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from neumann.analyze import backend as backend_mod
from neumann.analyze import cards as cards_mod
from neumann.analyze import checklist as checklist_mod
from neumann.analyze import extract as extract_mod
from neumann.analyze import queries as queries_mod
from neumann.analyze import review as review_mod
from neumann.analyze import rules
from neumann.analyze import validate as validate_mod
from neumann.analyze.backend import EvidenceBackend, Hit
from neumann.llm import LLMProvider, make_llm, provider_generator, task_options
from neumann.models import (
    Excerpt,
    PlanDocument,
    PremortemResult,
    RiskCard,
    SimilarWork,
    StageStatus,
)

PIPELINE_VERSION = "neumann-e3-l1w"
DEFAULT_K = 10
FITNESS_MISSING = "적합성 모듈 없음(E3-L1c 미병합) — astra ①의 연구계획서 판정으로 대신"
# v1 단계: (단계 이름 = LLM task 이름, 화면 단계 묶음). 이 순서로 붙인다(체크리스트 뒤에 검증해야 행동도 판정한다).
V1_STAGES: tuple[tuple[str, str], ...] = (
    ("expected_review", "REVIEW"),
    ("checklist", "ACTION"),
    ("semantic_validate", "ACTION"),
)
# v1 단계의 입력 의존(코드로 확인, E3-L1y). 값 = 결과를 입력으로 쓰는 앞 단계(최대 1개, V1_STAGES에서 앞선 것).
# - expected_review: 카드·근거·계획서·유사 연구 수만 읽는다(review.usable_cards·build_review_prompt·gate_sentences).
# - checklist: 카드·근거·계획서만 읽는다(checklist.build_checklist).
# - semantic_validate: result.checklist(행동)를 판정한다(validate.validate_cards) → 체크리스트 뒤.
V1_DEPENDS: dict[str, tuple[str, ...]] = {
    "expected_review": (),
    "checklist": (),
    "semantic_validate": ("checklist",),
}
V1_PARALLEL = True  # False면 E3-L1w처럼 V1_STAGES 순서로 차례로 돈다(비교 시험·비상용)

# 진행 보고 콜백: (단계 이름, 상태, 그 단계 소요 초). 상태는 "running"(시작) 또는 StageStatus.state.
StageCallback = Callable[[str, str, float], Any]

log = logging.getLogger(__name__)

_PHONE = re.compile(r"(?<!\d)(?:\+?82[- ]?)?0\d{1,2}-\d{3,4}-\d{4}(?!\d)")
_RRN = re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)")


def mask_extra_pii(text: str) -> tuple[str, int]:
    """models.redact_pii(이메일·ORCID)에 더해 전화번호·주민등록번호 형태를 가린다(최소판)."""
    n = 0

    def sub(pattern: re.Pattern[str], token: str, s: str) -> str:
        nonlocal n
        out, k = pattern.subn(token, s)
        n += k
        return out

    text = sub(_RRN, "[ID]", text)
    text = sub(_PHONE, "[PHONE]", text)
    return text, n


# ── 응답에 나가는 문구 정리(SEC-1 S-04) ──────────────────────────────────
# 결과(stages.detail, notices, 사유)에는 사용자용 짧은 문구와 분류만 싣는다. 예외 원문·경로·요청 정보는
# 서버 로그에만 남기고(`_log_exception`: 예외 종류와 파일:줄, 메시지 없음), 키·계획서 본문은 로그에도 쓰지 않는다.
# 아래 정리는 마지막 안전망이다: 절대 경로와 키 모양 문자열을 지운다.
_ABS_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\|/(?:home|Users|root|mnt|var|tmp|opt|srv|etc|usr)/)[^\s'\"<>|;,)]*"
)
_KEYLIKE = re.compile(r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_\-]{8,}|\bBearer\s+\S+|\b[A-Za-z0-9_\-]{40,}\b")
MAX_DETAIL_CHARS = 400
_SEARCH_STATUS_KEYS = (
    "backend", "degraded", "dense_model", "device", "alpha", "score_floor", "n_queries", "n_works", "n_hits",
    "n_excluded", "elapsed_s", "top_score",
)
MOCK_NOTICE = "mock provider(테스트용) 결과 — 실제 astra 분석이 아니다"


def safe_text(text: str | None) -> str | None:
    """응답에 싣기 전 문구 정리: 절대 경로 → [path], 키 모양 → [redacted], 길이 상한."""
    if text is None:
        return None
    text = _ABS_PATH.sub("[path]", str(text))
    text = _KEYLIKE.sub("[redacted]", text)
    return text[:MAX_DETAIL_CHARS]


def _log_exception(where: str, exc: BaseException) -> None:
    """서버 로그: 예외 종류와 발생 위치(파일 이름:줄)만. 메시지는 계획서 본문·키를 담을 수 있어 쓰지 않는다."""
    frames = traceback.extract_tb(exc.__traceback__)[-3:]
    trail = " <- ".join(f"{Path(f.filename).name}:{f.lineno}" for f in reversed(frames))
    log.error("%s 실패: %s @ %s", where, type(exc).__name__, trail)


def _emit(on_stage: StageCallback | None, name: str, state: str, elapsed_s: float) -> None:
    """진행 보고. 콜백이 실패해도 분석은 계속한다(종류만 로그)."""
    if on_stage is None:
        return
    try:
        on_stage(name, state, float(elapsed_s))
    except Exception as exc:  # noqa: BLE001 — 진행 표시 오류로 분석을 멈추지 않는다
        log.warning("on_stage 콜백 실패(무시): %s", type(exc).__name__)


@dataclass
class _Run:
    stages: list[StageStatus] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    on_stage: StageCallback | None = None

    def emit(self, name: str, state: str, elapsed_s: float = 0.0) -> None:
        _emit(self.on_stage, name, state, elapsed_s)

    @contextmanager
    def stage(self, name: str, phase: str):
        rec: dict[str, Any] = {"state": "ok", "detail": None, "impl": None, "counts": {}}
        self.emit(name, "running")
        t0 = time.perf_counter()
        try:
            yield rec
        except Exception as exc:  # noqa: BLE001 — 예외로 죽지 않는다
            _log_exception(f"단계 {name}", exc)
            rec["state"] = "error"
            rec["detail"] = f"내부 오류({type(exc).__name__}) — 이 단계를 건너뜀"
        finally:
            dt = time.perf_counter() - t0
            self.timings[name] = round(dt, 3)
            counts = {k: int(v) for k, v in rec["counts"].items()}
            detail = safe_text(rec["detail"])
            self.stages.append(
                StageStatus(stage=name, state=rec["state"], detail=detail, phase=phase, impl=rec["impl"],
                            elapsed_s=round(dt, 3), counts=counts)
            )
            if rec["state"] in ("degraded", "error"):
                self.notice(f"[{name}] {rec['state']}: {detail}")
            self.emit(name, rec["state"], round(dt, 3))

    def fill(self, rec: dict[str, Any], stage: StageStatus) -> None:
        """모듈이 만든 단계 기록(StageStatus)을 이 단계의 기록으로 옮긴다(소요 시간은 여기서 잰다)."""
        rec.update(state=stage.state, detail=stage.detail, impl=stage.impl, counts=dict(stage.counts))

    def skip(self, name: str, phase: str, why: str) -> None:
        self.stages.append(StageStatus(stage=name, state="skipped", detail=safe_text(why), phase=phase))
        self.timings[name] = 0.0
        self.emit(name, "skipped", 0.0)

    def notice(self, text: str) -> None:
        self.notices.append(safe_text(text) or "")


def _load_settings() -> tuple[Any, str | None]:
    try:
        from neumann.config import get_settings

        return get_settings(), None
    except Exception as exc:  # noqa: BLE001 — 설정 오류도 결과에 남기고 계속한다
        return None, f"설정 로드 실패({type(exc).__name__}), 환경변수·기본값으로 진행"


def _default_cache_dir(settings: Any) -> Path | None:
    """캐시 뿌리(`data/cache`). 지적 추출은 `extract/`, 검색어는 `queries/` 아래에 둔다."""
    data_dir = getattr(settings, "data_dir", None)
    return Path(data_dir) / "cache" if data_dir else None


def _load_fitness() -> Any | None:
    """적합성 모듈(E3-L1c). 아직 병합 전이면 None(그 단계는 skipped로 남긴다)."""
    try:
        from neumann.analyze import fitness  # type: ignore[attr-defined]
    except ImportError:
        return None
    return fitness


def _llm_call_for(llm: LLMProvider, task: str, settings: Any) -> tuple[Any | None, dict[str, Any], str | None]:
    """provider → 주입용 llm_call(`review.provider_llm_call`). (llm_call 또는 None, 호출 옵션, 못 만든 사유).

    생성 주체는 provider의 `generator` 속성(또는 이름 대응)에서만 정한다. 모르면 LLM을 부르지 않는다(규칙 경로).
    """
    opts = task_options(task, settings)
    try:
        gen = provider_generator(llm)
        call = review_mod.provider_llm_call(llm, task=task, timeout_s=opts["timeout_s"], generator=gen)
    except ValueError:
        return None, opts, f"provider {getattr(llm, 'name', '?')}의 생성 주체를 알 수 없어 LLM을 부르지 않았다"
    return call, opts, None


LOW_SIMILARITY_FLOOR = 0.0  # 짧은 입력에서 하한을 넘은 논문이 없을 때 다시 찾는 하한(= 하한 없음, 상위 k편)
# 적합성 보류 + 검색어 단계 "계획서 아님"인 경고 단계 입력을 진행시키는 유사 연구 근거 기준(E3-L1s 실측, bge-m3 하이브리드).
# 관련도 = max(dense, score)(E2 하한과 같은 값). 무관한 글 8건(조리법·여행·광고·일기) 상위 관련도 최대 0.426·0.50 이상 0편,
# 경고 단계 입력 16건(300~600자 직접 작성 15 + 백테스트 SFCH) 최소 0.602·0.50 이상 최소 7편(300자 기준 전 보정 24건도
# 최소 0.541·6편). 보고서 docs/reports/E3-L1s.md 표.
RESEARCH_GATE_MIN_TOP = 0.50
RESEARCH_GATE_MIN_WORKS = 3


def _search_strength(hits: list[Hit]) -> tuple[float | None, int]:
    """(상위 관련도, 관련도 RESEARCH_GATE_MIN_TOP 이상 논문 수). 관련도 = max(dense, score)."""
    rels = [max(h.score, h.dense or 0.0) for h in hits]
    return (max(rels) if rels else None), sum(1 for r in rels if r >= RESEARCH_GATE_MIN_TOP)


def _search_below_floor(backend: EvidenceBackend, queries: list[str], k: int,
                        exclude: set[str] | None) -> list[Hit] | None:
    """점수 하한 없이 상위 k편(백엔드가 score_floor 인자를 받을 때만). 못 하면 None."""
    try:
        params = inspect.signature(backend.search).parameters
    except (TypeError, ValueError):
        return None
    if "score_floor" not in params:
        return None
    return backend.search(queries, k=k, exclude_work_ids=exclude, score_floor=LOW_SIMILARITY_FLOOR)  # type: ignore[call-arg]


def _on_topic_rule_signal(fit: dict[str, Any]) -> bool:
    """적합성 모듈의 규칙 신호가 '무관한 글'(unfit)이 아니다. 규칙 신호가 없으면(가짜 모듈 등) False."""
    rule = fit.get("rule")
    return isinstance(rule, dict) and rule.get("verdict") in ("fit", "uncertain")


def run_premortem(
    plan_text: str,
    *,
    session_id: str | None = None,
    llm: LLMProvider | None = None,
    provider: str | None = None,
    backend: EvidenceBackend | None = None,
    settings: Any = None,
    k: int = DEFAULT_K,
    exclude_work_ids: set[str] | None = None,
    min_similarity: float = 0.0,
    cache_dir: Path | None | str = "default",
    on_stage: StageCallback | None = None,
) -> PremortemResult:
    """계획서 한 건을 분석한다. 예외로 죽지 않고 강등을 기록한다.

    llm/provider: 주입한 provider가 우선, 없으면 provider 이름("openai"|"mock"|"off"), 없으면 설정.
    backend: 근거 저장소. 없으면 E2 실색인(`IndexBackend`). fixture는 명시할 때만.
    exclude_work_ids: 백테스트 누출 제거용(검색에서 뺀다).
    cache_dir: 캐시 뿌리(기본 `data/cache`, None이면 캐시 끔). 추출은 `extract/`, 검색어는 `queries/`.
    on_stage: 진행 보고 콜백 `on_stage(stage, state, elapsed_s)`. 단계를 시작할 때 ("이름", "running", 0.0),
      끝날 때 ("이름", 최종 상태, 그 단계 소요 초). 건너뛴 단계는 끝 보고("skipped")만. 결과의 stages마다 끝 보고가
      정확히 한 번 온다. 동시에 도는 v1 단계도 이 함수를 부른 스레드에서 차례로 부른다(콜백에 잠금 불필요).
      콜백 예외는 무시한다(분석은 계속). None이면 보고하지 않는다(기존 호출과 같다).
    """
    t_start = time.perf_counter()
    run = _Run(on_stage=on_stage)
    session_id = session_id or uuid.uuid4().hex
    settings_note = None
    if settings is None:
        settings, settings_note = _load_settings()
    if settings_note:
        run.notice(settings_note)
    if llm is None:
        llm = make_llm(settings, provider)
    if cache_dir == "default":
        cache_dir = _default_cache_dir(settings)
    cache_root = Path(cache_dir) if isinstance(cache_dir, str | Path) else None
    stage_limits: dict[str, float] = {}

    extras: dict[str, Any] = {
        "plan_checks": {},
        "risk_synthesis": {"score_formula": cards_mod.SCORE_FORMULA},
        "verification": {},
        "axes": {},
        "domain": None,
    }
    plan: PlanDocument | None = None
    hits: list[Hit] = []
    works_meta: dict[str, Any] = {}
    cards: list[RiskCard] = []
    evidence: dict[str, Excerpt] = {}
    no_card_reason: str | None = None

    # 1. 정규화 ────────────────────────────────────────────────────────────
    with run.stage("plan_normalize", "INPUT") as st:
        st["impl"] = "neumann.models:PlanDocument.from_text"
        masked, n_masked = mask_extra_pii(plan_text or "")
        plan = PlanDocument.from_text(masked, session_id)
        n_nonblank = sum(1 for ln in plan.lines if ln.text.strip())
        st["counts"] = {"lines": len(plan.lines), "nonblank_lines": n_nonblank, "pii_masked_extra": n_masked}
        if n_nonblank == 0:
            st["state"], st["detail"] = "error", "빈 입력"
            no_card_reason = "입력이 비어 있다"

    if plan is None:  # 정규화 자체가 실패
        plan = PlanDocument.from_text("", session_id)
        no_card_reason = no_card_reason or "계획서 정규화 실패"

    # 2. 입력 적합성(E3-L1c) — 검색 전에. 분석하지 않음(unfit)이면 카드 0장·사유로 끝 ─────────────
    fit: dict[str, Any] | None = None
    iq: dict[str, Any] = {}
    iq_level = "unknown"  # 입력 분량 단계(E3-L1s): reject|warn|ok, 적합성 모듈이 없거나 실패하면 unknown
    fitness_mod = _load_fitness()
    if no_card_reason is not None:
        run.skip("fitness", "INPUT", no_card_reason)
    elif fitness_mod is None:
        run.skip("fitness", "INPUT", FITNESS_MISSING)
    else:
        with run.stage("fitness", "INPUT") as st:
            call, opts, why = _llm_call_for(llm, "fitness", settings)
            stage_limits["fitness"] = opts["timeout_s"]
            fit = fitness_mod.assess_fitness(plan, call, effort=opts["effort"])
            run.fill(st, fitness_mod.fitness_stage(fit))
            if why:
                st["detail"] = f"{st['detail']}; {why}"
        if fit is not None:
            extras["plan_checks"]["fitness"] = fit
            got_iq = fit.get("input_quality")
            if isinstance(got_iq, dict):
                iq = got_iq
                extras["plan_checks"]["input_quality"] = iq
                iq_level = str(iq.get("level") or "ok")
            if fit.get("notice"):
                run.notice(fit["notice"])
            if iq_level == "warn" and iq.get("message"):
                run.notice(iq["message"])
            if not fit.get("analyze", True) and fit.get("decided_by") == "precheck":
                msg = (iq.get("message") if iq else None) or "입력이 짧아 연구계획서로 분석하지 않습니다."
                no_card_reason = f"{msg} (규칙 판정, LLM 호출 없음; 검색 안 함)"
            elif not fit.get("analyze", True):
                no_card_reason = f"입력이 연구계획서가 아니다({fit.get('generator')} 판단: {fit.get('reason')}); 검색 안 함"
                extras["plan_checks"]["suitability"] = {
                    "is_research_plan": False,
                    "reason": fit.get("reason"),
                    "reason_lines": [],
                    "generator": fit.get("generator"),
                    "source": "fitness",
                    "verdict": fit.get("verdict"),
                }

    # 3. astra ① 검색어·축 ──────────────────────────────────────────────────
    qp: queries_mod.QueryPlan | None = None
    if no_card_reason is None:
        with run.stage("query_axes", "INPUT") as st:
            stage_limits["query_axes"] = task_options(queries_mod.TASK, settings)["timeout_s"]
            qp = queries_mod.make_queries(
                plan, llm, settings, cache_dir=cache_root / "queries" if cache_root is not None else None
            )
            hit = bool(qp.cache.get("hit"))
            if qp.generator == "rule":
                st["impl"] = "fallback:rules.fallback_queries"
            else:
                st["impl"] = f"cache:{llm.name}:{qp.model}" if hit else f"{llm.name}:{llm.model}"
            st["counts"] = {"queries": len(qp.queries), "axes": len(qp.axes), "cache_hit": int(hit)}
            if qp.fallback_reason:
                st["state"], st["detail"] = "degraded", f"비상 규칙 경로: {qp.fallback_reason}"
            elif hit:
                st["detail"] = (
                    f"검색어 캐시 적중({qp.generator}:{qp.model}, {qp.cache.get('created_at')} 생성); "
                    f"연구계획서={qp.is_research}"
                )
            else:
                st["detail"] = f"{qp.llm.reason() if qp.llm else ''}; 연구계획서={qp.is_research}"
            extras["axes"] = qp.axes
            extras["domain"] = qp.domain
            extras["plan_checks"]["suitability"] = {
                "is_research_plan": qp.is_research,
                "reason": qp.reason,
                "reason_lines": qp.reason_lines,
                "generator": qp.generator,
                "research_word_hits": rules.research_signal(plan),
            }
            extras["plan_checks"]["queries"] = {
                "queries": qp.queries, "generator": qp.generator, "notes": qp.notes, "cache": dict(qp.cache),
            }
        if qp is None:
            no_card_reason = "검색어·축 단계 오류로 분석하지 못했다"
    else:
        run.skip("query_axes", "INPUT", no_card_reason)

    # 4. 검색 ──────────────────────────────────────────────────────────────
    if backend is None and no_card_reason is None:
        try:
            backend = backend_mod.make_backend()
        except Exception as exc:  # noqa: BLE001
            _log_exception("근거 저장소 열기", exc)
            backend = None
            run.skip("search", "EVIDENCE", f"근거 저장소 없음({type(exc).__name__})")
            run.notice("[search] 근거 저장소(E2 색인)를 열 수 없다")
            no_card_reason = "유사 연구 색인을 열 수 없어 분석하지 못했다"
    if backend is not None and qp is not None and no_card_reason is None:
        with run.stage("search", "EVIDENCE") as st:
            st["impl"] = getattr(backend, "impl", backend.name)
            search_queries = qp.queries or rules.fallback_queries(plan)
            queries_source = "llm" if qp.queries else "rule"  # 검색어 단계가 검색어를 안 주면 규칙 대체(표시한다, E5-L2d)
            hits = backend.search(search_queries, k=k, exclude_work_ids=exclude_work_ids)
            low_similarity = False
            on_topic = fit is not None and _on_topic_rule_signal(fit) and fit.get("verdict") != "unfit"
            if not hits and iq_level == "warn" and on_topic:  # E3-L1s: 짧은 입력은 하한 아래라도 상위 k편을 "낮은 유사도"로
                low = _search_below_floor(backend, search_queries, k, exclude_work_ids)
                if low:
                    hits, low_similarity = low, True
            top = max((h.score for h in hits), default=None)
            kept = [h for h in hits if h.score >= min_similarity]
            st["counts"] = {"hits": len(hits), "kept": len(kept), "queries": len(search_queries),
                            "low_similarity": int(low_similarity)}
            st["detail"] = f"상위 점수 {top:.3f}" if top is not None else "검색 결과 0건"
            if queries_source == "rule":
                st["detail"] += f"; 검색어 {len(search_queries)}개는 규칙 대체(검색어 단계가 검색어를 주지 않음)"
                run.notice(f"검색어 단계가 검색어를 주지 않아 규칙 검색어 {len(search_queries)}개(계획서의 영문 기술어·첫 줄)로 "
                           "유사 연구를 찾았다(검색어 규칙 대체).")
            if low_similarity and top is not None:
                st["detail"] += f"; 점수 하한을 넘은 논문이 없어 하한 없이 상위 {len(hits)}편을 낮은 유사도로 사용"
                run.notice(f"유사 연구가 검색 점수 하한 아래라 상위 {len(hits)}편을 '낮은 유사도'로 표시하고 분석했다"
                           f"(상위 점수 {top:.3f}). 결과가 이 계획서와 멀 수 있다.")
            # E2 검색 상태: 사유 문자열(경로가 들어갈 수 있다)은 빼고 공개해도 되는 키만 싣는다.
            raw_status = backend.status() if hasattr(backend, "status") else {}
            be_status = {k: raw_status[k] for k in _SEARCH_STATUS_KEYS if k in raw_status}
            if be_status.get("degraded"):
                st["state"] = "degraded"
                st["detail"] += f"; 검색 강등(백엔드 {be_status.get('backend', '?')}, 임베딩 없이 어휘 검색)"
            extras["plan_checks"]["search"] = {
                "top_score": top,
                "min_similarity": min_similarity,
                "scores": [round(h.score, 4) for h in hits],
                "backend_status": be_status,
                "queries_source": queries_source,
                "low_similarity": low_similarity,
            }
            hits = kept
            for h in hits:
                works_meta[h.work_id] = backend.get_work(h.work_id)
            if not hits:
                no_card_reason = (
                    f"유사 연구를 찾지 못했다(상위 점수 {top:.3f}, 하한 {min_similarity})" if top is not None
                    else "유사 연구 검색 결과가 0건이다"
                )
    elif "search" not in run.timings:
        run.skip("search", "EVIDENCE", no_card_reason or "앞 단계 실패")

    # 연구계획서가 아니면 추출·합성을 하지 않는다. 사유에 판정 근거와 검색 점수를 함께 남긴다.
    # 적합성 판정이 있으면 그것이 기준이다: fit이면 astra ①의 판정과 무관하게 진행, uncertain이면 astra ①도
    # 연구계획서가 아니라고 볼 때만 멈춘다. 적합성 판정이 없으면(모듈 없음·오류) astra ①의 판정만 본다(E3-L0).
    fit_verdict = fit.get("verdict") if fit is not None else None
    # E3-L1s: 적합성 보류(uncertain)라도 규칙 신호가 무관한 글이 아니면 멈추지 않는다(연구 배경만 적은 짧은 초록 등).
    # 백테스트 n=5에서 짧은 입력 3편이 여기서 카드 0장으로 끝났다(적합성 보류 + 검색어 단계 "계획서 아님").
    gate_pass = False
    gate_why = ""
    if qp is not None and not qp.is_research and fit_verdict == "uncertain" and fit is not None and no_card_reason is None:
        rule_sig = fit.get("rule") or {}
        low_sim = bool(extras["plan_checks"].get("search", {}).get("low_similarity"))
        top_rel, n_strong = _search_strength(hits)
        checks = {
            "input_warn": iq_level == "warn",
            "rule_on_topic": _on_topic_rule_signal(fit),
            "search_strong": (top_rel is not None and top_rel >= RESEARCH_GATE_MIN_TOP
                              and n_strong >= RESEARCH_GATE_MIN_WORKS and not low_sim),
        }
        gate_pass = all(checks.values())
        gate_why = ", ".join(k for k, v in checks.items() if not v)
        extras["plan_checks"]["research_gate"] = {
            "passed": gate_pass,
            "status": "proceeded_on_similar_work_evidence" if gate_pass else "stopped",
            "note": "적합성 보류였으나 유사 연구 근거로 진행" if gate_pass else None,
            "failed_checks": [k for k, v in checks.items() if not v],
            "fitness_verdict": fit_verdict, "query_axes_is_research": False,
            "rule_verdict": rule_sig.get("verdict"), "rule_elements": rule_sig.get("n_elements"),
            "top_relevance": round(top_rel, 4) if top_rel is not None else None, "n_strong_works": n_strong,
            "min_top_relevance": RESEARCH_GATE_MIN_TOP, "min_strong_works": RESEARCH_GATE_MIN_WORKS,
        }
        if gate_pass:
            extras["plan_checks"].setdefault("suitability", {})["thin_input"] = True  # E5-L2d 표기와 같은 키
            run.notice(f"적합성 보류였으나 유사 연구 근거로 진행: 상위 관련도 {top_rel:.3f}(기준 {RESEARCH_GATE_MIN_TOP}), "
                       f"기준 이상 유사 연구 {n_strong}편. 검색어 단계도 연구계획서로 보지 않았으니 결과 신뢰도가 낮다.")
    if qp is not None and not qp.is_research and fit_verdict in (None, "uncertain") and not gate_pass:
        search_info = extras["plan_checks"].get("search", {})
        top = search_info.get("top_score")
        score_s = (
            f"유사 연구 검색 상위 점수 {top:.3f}" if isinstance(top, float)
            else ("유사 연구 검색 결과 0건" if "search" in extras["plan_checks"] else "검색 안 함")
        )
        no_card_reason = f"입력이 연구계획서가 아니다({qp.generator} 판단: {qp.reason}); {score_s}"
        if fit_verdict == "uncertain":
            no_card_reason += f"; 적합성 판정 보류({fit.get('generator') if fit else '-'})"
            if gate_why:
                no_card_reason += f"; 진행 조건 미충족({gate_why})"

    # 5. astra ② 지적 추출 ─────────────────────────────────────────────────
    extraction: extract_mod.ExtractionResult | None = None
    if no_card_reason is None and backend is not None:
        with run.stage("extract_issues", "EVIDENCE") as st:
            tagger, tagger_impl = rules.make_rule_tagger()
            inputs = []
            for h in hits:
                w = works_meta.get(h.work_id)
                inputs.append((h.work_id, getattr(w, "title", None), backend.get_excerpts(h.work_id)))
            extraction = extract_mod.extract_issues(
                inputs, llm, tagger=tagger, settings=settings,
                cache_dir=cache_root / "extract" if cache_root is not None else None,
            )
            st["counts"] = extraction.counts()
            n_fb = len(extraction.fallback_batches)
            st["impl"] = f"{llm.name}:{llm.model}" + (f" + fallback:{tagger_impl}" if n_fb else "")
            rate = extraction.drop_rate()
            rate_s = f"폐기율 {rate:.1%}" if rate is not None else "폐기율 -"
            if n_fb:
                reasons = sorted({b.fallback_reason or "" for b in extraction.fallback_batches})
                st["state"] = "degraded"
                st["detail"] = f"비상 규칙 경로: {n_fb}/{len(extraction.batches)} 묶음 ({'; '.join(reasons)[:300]}); {rate_s}"
            else:
                st["detail"] = rate_s
            if not extraction.works_analyzed:
                no_card_reason = "유사 연구에 심사평 문장이 없다"
            # 폐기율(E5-L0 근거 연결 검사기가 이 키를 읽는다). LLM이 돌려준 지적 기준, 규칙 대체분은 따로.
            c = extraction.counts()
            extras["verification"].update(
                {
                    "findings_total": c["findings_total"],
                    "findings_kept": c["findings_kept"],
                    "findings_dropped": c["findings_dropped"],
                    "findings_drop_rate": rate,
                    "findings_drop_reasons": dict(sorted(extraction.drops.items())),
                    "findings_rule": c["findings_rule"],
                }
            )
        if extraction is None and no_card_reason is None:
            no_card_reason = "지적 추출 단계 오류"
    elif "extract_issues" not in run.timings:
        run.skip("extract_issues", "EVIDENCE", no_card_reason or "앞 단계 실패")

    # 6. astra ③ 카드 합성 ─────────────────────────────────────────────────
    synthesis: cards_mod.SynthesisResult | None = None
    if no_card_reason is None and extraction is not None:
        with run.stage("synthesize_cards", "RISK") as st:
            titles = {wid: getattr(w, "title", "") or "" for wid, w in works_meta.items()}
            similarity = {h.work_id: h.score for h in hits}
            short = iq_level == "warn"
            synthesis = cards_mod.synthesize_cards(
                plan, extraction.issues, titles, similarity, len(extraction.works_analyzed), llm, settings,
                short_input=short,
            )
            st["counts"] = synthesis.counts()
            if synthesis.fallback_reason:
                st["state"], st["impl"] = "degraded", "fallback:cards.rule_cards"
                st["detail"] = f"비상 규칙 경로: {synthesis.fallback_reason}"
            elif synthesis.generator == "none":
                st["state"], st["impl"] = "skipped", None
                st["detail"] = synthesis.no_card_reason
            else:
                st["impl"] = f"{llm.name}:{llm.model}"
                st["detail"] = synthesis.llm.reason() if synthesis.llm else None
            if short and not synthesis.cards and extraction.issues:
                # E3-L1s: 짧은 입력은 카드 0장으로 끝내지 않는다 → 분야 수준 카드(규칙 합성, LLM 결과라고 쓰지 않는다)
                first_reason = synthesis.no_card_reason
                field_syn = cards_mod.field_level_cards(plan, extraction.issues, similarity,
                                                        len(extraction.works_analyzed))
                extras["risk_synthesis"]["field_level"] = {
                    "used": bool(field_syn.cards), "first_generator": synthesis.generator,
                    "first_no_card_reason": first_reason, "cards": len(field_syn.cards),
                }
                if field_syn.cards:
                    synthesis = field_syn
                    st["state"], st["impl"] = "degraded", "fallback:cards.field_level_cards"
                    st["detail"] = (f"분야 수준 카드(규칙 합성) {len(field_syn.cards)}장: 짧은 입력에서 "
                                    f"카드 합성이 0장이라 대신함({first_reason or '사유 없음'})")
                    st["counts"] = {**st["counts"], "field_level_cards": len(field_syn.cards)}
                    run.notice("입력이 짧아 계획서 줄에 맞춘 위험카드가 나오지 않아, 유사 연구 심사평에서 반복된 "
                               f"위험 유형으로 분야 수준 카드 {len(field_syn.cards)}장을 규칙으로 만들었다(LLM 생성 아님).")
            cards, evidence = synthesis.cards, synthesis.evidence
            no_card_reason = synthesis.no_card_reason if not cards else None
        if synthesis is None:
            no_card_reason = no_card_reason or "카드 합성 단계 오류"
    elif "synthesize_cards" not in run.timings:
        run.skip("synthesize_cards", "RISK", no_card_reason or "앞 단계 실패")

    # 7. 원문 대조 ────────────────────────────────────────────────────────
    if cards and backend is not None:
        verified = False
        with run.stage("verify_evidence", "REVIEW") as st:
            st["impl"] = "neumann.models:Excerpt.verify_against"
            cards, evidence, vstats = _verify(cards, evidence, backend)
            verified = True
            st["counts"] = vstats
            extras["verification"].update(
                {"quotes_total": vstats["quotes_total"], "quotes_verified": vstats["quotes_verified"],
                 "linkage_rate": vstats["quotes_verified"] / vstats["quotes_total"] if vstats["quotes_total"] else None}
            )
            if vstats["quotes_total"] != vstats["quotes_verified"] or vstats["cards_dropped"]:
                st["state"] = "degraded"
                st["detail"] = f"원문 대조 실패 근거 {vstats['quotes_total'] - vstats['quotes_verified']}건 제거, 카드 {vstats['cards_dropped']}장 탈락"
            else:
                st["detail"] = f"근거 {vstats['quotes_verified']}/{vstats['quotes_total']} 원문 일치"
            if not cards:
                no_card_reason = "카드 근거가 원문 대조를 통과하지 못해 모두 탈락했다"
        if not verified:  # 대조를 끝내지 못한 카드는 내보내지 않는다
            cards, evidence = [], {}
            no_card_reason = "원문 대조 단계 오류로 카드를 내보내지 않았다"
    else:
        run.skip("verify_evidence", "REVIEW", "카드 없음")

    # 결과 ─────────────────────────────────────────────────────────────────
    if not cards:
        reason = safe_text(no_card_reason) or "카드 0장(사유 미상)"
        run.notice(f"위험카드 0장: {reason}")
        extras["risk_synthesis"]["no_card_reason"] = reason
    # SEC-1 S-05: mock provider 결과(또는 mock 카드)는 정상(ok)으로 두지 않는다.
    is_mock = llm.name == "mock" or any(c.generator.value == "mock" for c in cards)
    if is_mock:
        run.notice(MOCK_NOTICE)
    if synthesis is not None:
        extras["risk_synthesis"].update(
            {
                "generator": synthesis.generator,
                "fallback_reason": synthesis.fallback_reason,
                "pool_size": synthesis.pool_size,
                "drops": dict(synthesis.drops),
                "tags": [synthesis.tags[x].tag().model_dump(mode="json") for c in cards for x in c.evidence if x in synthesis.tags],
                "notes": list(synthesis.notes),
            }
        )
    similar = [
        SimilarWork(
            work_id=h.work_id,
            similarity=max(-1.0, min(1.0, h.score)),
            title=getattr(works_meta.get(h.work_id), "title", None),
            url=getattr(works_meta.get(h.work_id), "url", None),
            venue=getattr(works_meta.get(h.work_id), "venue", None),
            year=getattr(works_meta.get(h.work_id), "year", None),
        )
        for h in hits
    ]
    manifest = {
        "pipeline_version": PIPELINE_VERSION,
        "llm_provider": llm.name,
        "llm_model": llm.model,
        "backend": getattr(backend, "impl", getattr(backend, "name", None)) if backend is not None else None,
        "prompt_versions": [queries_mod.PROMPT_VERSION, extract_mod.PROMPT_VERSION, cards_mod.PROMPT_VERSION,
                            review_mod.REVIEW_VERSION],
        "timings_s": run.timings,
        "total_s": round(time.perf_counter() - t_start, 3),
        "query_cache": dict(qp.cache) if qp is not None else {"enabled": False, "hit": False, "stored": False},
        "input_quality": {"level": iq_level, "status": iq.get("status") if iq else None},
    }
    try:
        result = PremortemResult(
            session_id=session_id,
            plan_id=plan.plan_id,
            status="degraded" if is_mock else "ok",  # 단계 강등이 있으면 모델이 degraded로 올린다
            pipeline_version=PIPELINE_VERSION,
            plan=plan,
            similar_works=similar,
            evidence=list(evidence.values()),
            risk_cards=cards,
            stages=run.stages,
            notices=run.notices,
            plan_stats={"lines": len(plan.lines), "chars": len(plan.text)},
            axes=extras["axes"],
            domain=extras["domain"],
            plan_checks=extras["plan_checks"],
            verification=extras["verification"],
            risk_synthesis=extras["risk_synthesis"],
            manifest=manifest,
        )
    except Exception as exc:  # noqa: BLE001 — 조립 실패도 결과로 돌려준다
        _log_exception("결과 조립", exc)
        stages = [*run.stages, StageStatus(stage="assemble", state="error", detail=f"내부 오류({type(exc).__name__})")]
        run.emit("assemble", "error", 0.0)
        return PremortemResult(
            session_id=session_id, plan_id=plan.plan_id, status="error", stages=stages,
            notices=[*run.notices, "결과 조립 실패"], manifest=manifest,
            risk_synthesis={"no_card_reason": "결과 조립 실패"},
        )

    # 8~10. 예상 심사평 ∥ (체크리스트 → 2차 검증)(카드가 없으면 각 모듈이 호출 없이 skipped로 남긴다) ────────
    parallel = bool(V1_PARALLEL)
    t_v1 = time.perf_counter()
    result = _attach_v1(result, plan, llm, settings, stage_limits, parallel=parallel, on_stage=on_stage)
    manifest = {
        **result.manifest,
        "timings_s": {s.stage: s.elapsed_s for s in result.stages},
        "total_s": round(time.perf_counter() - t_start, 3),
        "stage_limits_s": stage_limits,
        "v1_parallel": parallel,  # True면 v1 단계 timings_s의 합이 v1_wall_s보다 클 수 있다(동시 실행)
        "v1_wall_s": round(time.perf_counter() - t_v1, 3),
    }
    return result.model_copy(update={"manifest": manifest})


def _v1_stage(result: PremortemResult, task: str, plan: PlanDocument, call: Any, effort: str) -> PremortemResult:
    if task == "expected_review":
        return review_mod.attach_expected_review(result, call, effort=effort)
    if task == "checklist":
        return checklist_mod.attach_checklist(result, plan, call, effort=effort)
    if task == "semantic_validate":
        return validate_mod.attach_validation(result, plan, call, effort=effort)
    raise ValueError(f"모르는 v1 단계: {task}")


_Prepared = tuple[Any, dict[str, Any], str | None]  # (llm_call, 호출 옵션, 못 만든 사유) — _llm_call_for의 반환
_STATUS_RANK = {"ok": 0, "degraded": 1, "error": 2}
_MERGE_SKIP = frozenset({"stages", "notices", "status"})


def _v1_graph_errors(
    stages: tuple[tuple[str, str], ...] = V1_STAGES, depends: dict[str, tuple[str, ...]] | None = None
) -> list[str]:
    """의존 그래프 검사: 단계마다 의존은 최대 1개이고 V1_STAGES에서 앞선 단계여야 한다(사슬·나무 모양)."""
    depends = V1_DEPENDS if depends is None else depends
    names = [n for n, _ in stages]
    errs: list[str] = []
    for i, name in enumerate(names):
        deps = depends.get(name)
        if deps is None:
            errs.append(f"{name}: V1_DEPENDS에 없음")
        elif len(deps) > 1:
            errs.append(f"{name}: 의존이 둘 이상 {deps}")
        elif deps and deps[0] not in names[:i]:
            errs.append(f"{name}: 의존 {deps[0]}이 앞 단계가 아님")
    return errs


def _v1_task(result: PremortemResult, task: str, phase: str, plan: PlanDocument, prepared: _Prepared) -> PremortemResult:
    """v1 단계 하나를 붙인 새 결과(E3-L1w 순차 루프의 한 바퀴와 같은 처리).

    단계마다 따로 막는다: 모듈이 예외로 죽으면 그 단계만 error로 남기고 입력 결과를 그대로 넘긴다.
    모듈이 LLM 실패로 규칙 경로·미검증으로 물러나면 그 단계만 degraded(모듈의 단계 기록)다.
    화면 단계 묶음(phase)은 파이프라인 기준(REVIEW·ACTION)으로 맞추고, 강등이면 notices에 한 줄 남긴다.
    """
    call, opts, why = prepared
    t0 = time.perf_counter()
    before = len(result.notices)
    try:
        new = _v1_stage(result, task, plan, call, opts["effort"])
    except Exception as exc:  # noqa: BLE001 — 이 단계만 error로 남기고 계속한다
        _log_exception(f"단계 {task}", exc)
        stage = StageStatus(
            stage=task, state="error", detail=f"내부 오류({type(exc).__name__}) — 이 단계를 건너뜀", phase=phase,
            elapsed_s=round(time.perf_counter() - t0, 3),
        )
        notices = [*result.notices, safe_text(f"[{task}] error: {stage.detail}") or ""]
        return checklist_mod.with_stage(result, stage, notices=notices)
    # 모듈이 'llm_failed'처럼 분류만 남기면 어댑터가 받은 실패 사유(시간 초과 등, 비밀값 없음)를 덧붙인다.
    # llm_call은 단계마다 따로 만든다(_llm_call_for) → 동시에 돌아도 다른 단계의 last_error·model이 섞이지 않는다.
    last_error = getattr(call, "last_error", None)
    stages: list[StageStatus] = []
    for s in new.stages:
        if s.stage == task:
            extra = last_error if s.state == "degraded" and last_error and last_error not in (s.detail or "") else None
            detail = safe_text("; ".join(x for x in (s.detail, extra and f"마지막 호출: {extra}", why) if x)) or None
            s = s.model_copy(update={"phase": phase, "detail": detail})
            if s.state in ("degraded", "error") and len(new.notices) == before:
                new = new.model_copy(update={"notices": [*new.notices, safe_text(f"[{task}] {s.state}: {detail}") or ""]})
        stages.append(s)
    return new.model_copy(update={"stages": stages})


def _emit_done(on_stage: StageCallback | None, result: PremortemResult, task: str) -> None:
    st = next((s for s in result.stages if s.stage == task), None)
    _emit(on_stage, task, st.state if st is not None else "error", st.elapsed_s if st is not None else 0.0)


def _attach_v1(
    result: PremortemResult,
    plan: PlanDocument,
    llm: LLMProvider,
    settings: Any,
    stage_limits: dict[str, float],
    *,
    parallel: bool = True,
    on_stage: StageCallback | None = None,
) -> PremortemResult:
    """예상 심사평(E3-L1a)·체크리스트·2차 검증(E3-L1b)을 붙인다.

    parallel=True: 의존 그래프(V1_DEPENDS)대로 동시에 돌리고 V1_STAGES 순서로 합친다(순차 실행과 같은 결과).
    parallel=False: V1_STAGES 순서로 차례로(E3-L1w 동작).
    llm_call·호출 옵션·상한 기록은 모두 이 스레드에서 미리 만든다(공유 dict에 작업 스레드가 쓰지 않는다).
    """
    prepared: dict[str, _Prepared] = {}
    for task, _phase in V1_STAGES:
        call, opts, why = _llm_call_for(llm, task, settings)
        stage_limits[task] = opts["timeout_s"]
        prepared[task] = (call, opts, why)
    errs = _v1_graph_errors()
    if not parallel or errs:
        if parallel:
            log.error("v1 의존 그래프 오류 → 순차 실행: %s", "; ".join(errs))
        for task, phase in V1_STAGES:
            _emit(on_stage, task, "running", 0.0)
            result = _v1_task(result, task, phase, plan, prepared[task])
            _emit_done(on_stage, result, task)
        return result
    return _attach_v1_parallel(result, plan, prepared, on_stage)


def _attach_v1_parallel(
    base: PremortemResult, plan: PlanDocument, prepared: dict[str, _Prepared], on_stage: StageCallback | None
) -> PremortemResult:
    """의존이 풀린 단계부터 작업 스레드에 넣는다. 진행 보고·합치기는 이 스레드에서만 한다."""
    order = {name: i for i, (name, _) in enumerate(V1_STAGES)}
    waiting = dict(V1_STAGES)  # 아직 시작 안 한 단계 → phase (V1_STAGES 순서)
    inputs: dict[str, PremortemResult] = {}
    outputs: dict[str, PremortemResult] = {}
    running: dict[Future[PremortemResult], str] = {}
    with ThreadPoolExecutor(max_workers=len(V1_STAGES), thread_name_prefix="neumann-v1") as pool:

        def launch_ready() -> None:
            for task in [t for t in waiting if all(d in outputs for d in V1_DEPENDS[t])]:
                phase = waiting.pop(task)
                deps = V1_DEPENDS[task]
                src = outputs[deps[0]] if deps else base
                inputs[task] = src
                _emit(on_stage, task, "running", 0.0)
                ctx = contextvars.copy_context()  # 요청 문맥(serving 등)을 작업 스레드에도 넘긴다
                running[pool.submit(ctx.run, _v1_task, src, task, phase, plan, prepared[task])] = task

        launch_ready()
        while running:
            done, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for fut in sorted(done, key=lambda f: order[running[f]]):
                task = running.pop(fut)
                outputs[task] = fut.result()
                _emit_done(on_stage, outputs[task], task)
            launch_ready()
    return _merge_v1(base, inputs, outputs)


def _merge_v1(
    base: PremortemResult, inputs: dict[str, PremortemResult], outputs: dict[str, PremortemResult]
) -> PremortemResult:
    """단계별 결과를 V1_STAGES 순서로 합친다 — 순차 실행(앞 결과를 다음 단계 입력으로)과 같은 결과가 되게.

    단계마다 자기 입력 대비 바뀐 필드만 옮긴다(딕셔너리 필드는 바뀐 키만). 단계 기록은 그 단계 것만, notices는
    그 단계가 뒤에 덧붙인 것만. status는 가장 나쁜 값(ok < degraded < error: 모듈은 강등만 한다).
    """
    names = {n for n, _ in V1_STAGES}
    stages = [s for s in base.stages if s.stage not in names]
    notices = list(base.notices)
    status = base.status
    update: dict[str, Any] = {}
    for task, _phase in V1_STAGES:
        src, out = inputs[task], outputs[task]
        stages.extend(s for s in out.stages if s.stage == task)
        n = len(src.notices)
        if out.notices[:n] == src.notices:
            notices.extend(out.notices[n:])
        else:  # 모듈이 앞 notices를 바꾼 경우(지금은 없다): 새로 생긴 문구만
            notices.extend(x for x in out.notices if x not in src.notices)
        if _STATUS_RANK.get(out.status, 2) > _STATUS_RANK.get(status, 2):
            status = out.status
        for name in type(out).model_fields:
            if name in _MERGE_SKIP:
                continue
            old, cur = getattr(src, name), getattr(out, name)
            if cur == old:
                continue
            if isinstance(old, dict) and isinstance(cur, dict):
                merged = dict(update.get(name, getattr(base, name)))
                merged.update({k: v for k, v in cur.items() if k not in old or old[k] != v})
                update[name] = merged
            else:
                update[name] = cur
    return base.model_copy(update={**update, "stages": stages, "notices": notices, "status": status})


def _verify(
    cards: list[RiskCard], evidence: dict[str, Excerpt], backend: EvidenceBackend
) -> tuple[list[RiskCard], dict[str, Excerpt], dict[str, int]]:
    """근거를 원문(심사평 전문)에 대조한다. 실패한 근거는 빼고, 불변식이 깨진 카드는 버린다."""
    sources: dict[str, str] = {}
    work_of: dict[str, str] = {}
    for card in cards:
        for wid in card.works:
            for r in backend.get_reviews(wid):
                sources[r.review_id] = r.text
                work_of[r.review_id] = wid
    ok_ids: set[str] = set()
    for ex_id, ex in evidence.items():
        src = sources.get(ex.source_id) if ex.source_kind == "review" else None
        if src is not None and ex.verify_against(src):
            ok_ids.add(ex_id)
    kept: list[RiskCard] = []
    dropped = 0
    for card in cards:
        ev = [x for x in card.evidence if x in ok_ids]
        works = list(dict.fromkeys(work_of.get(evidence[x].source_id, "") for x in ev))
        if len(ev) < cards_mod.MIN_EVIDENCE or len(works) < cards_mod.MIN_WORKS:
            dropped += 1
            continue
        kept.append(card if ev == card.evidence else card.model_copy(update={"evidence": ev, "works": works}))
    used = {x for c in kept for x in c.evidence}
    stats = {
        "quotes_total": len(evidence),
        "quotes_verified": len(ok_ids),
        "cards_in": len(cards),
        "cards_kept": len(kept),
        "cards_dropped": dropped,
    }
    return kept, {k: v for k, v in evidence.items() if k in used}, stats


# ── 명령줄 ────────────────────────────────────────────────────────────────


def summarize(result: PremortemResult) -> dict[str, Any]:
    """사람이 읽을 요약(보고서·수동 확인용)."""
    ev = {e.excerpt_id: e for e in result.evidence}
    return {
        "status": result.status,
        "cards": [
            {
                "risk_code": c.risk_code.value,
                "title": c.title,
                "generator": c.generator.value,
                "score": c.score.total,
                "plan_lines": c.why_applies.plan_lines,
                "why": c.why_applies.text,
                "works": c.works,
                "quotes": [ev[x].text[:160] for x in c.evidence if x in ev],
            }
            for c in result.risk_cards
        ],
        "similar_works": [(w.work_id, round(w.similarity, 3), (w.title or "")[:80]) for w in result.similar_works],
        "stages": [(s.stage, s.state, s.elapsed_s, s.detail) for s in result.stages],
        "no_card_reason": result.risk_synthesis.get("no_card_reason"),
        "verification": {k: v for k, v in result.verification.items() if k != "semantic"},
        "fitness": {k: fit.get(k) for k in ("verdict", "analyze", "generator", "status", "decided_by", "reason")}
        if (fit := result.plan_checks.get("fitness")) else None,
        "query_cache": result.manifest.get("query_cache"),
        "expected_review": {
            "generator": er.get("generator"), "model": er.get("model"), "status": er.get("status"),
            "reason": er.get("reason"), "audit": {k: er.get("audit", {}).get(k) for k in ("gen", "pass", "drop")},
            "sentences": {s: [x.get("t") for x in er.get(s, [])] for s in ("strength", "weakness", "request")},
        } if (er := result.expected_review) else None,
        "checklist": [
            {"item_id": it.get("item_id"), "card_id": it.get("card_id"), "generator": it.get("generator"),
             "plan_lines": it.get("plan_lines"), "action": it.get("action"),
             "verdict": (it.get("validation") or {}).get("verdict"), "card_verdict": it.get("card_verdict")}
            for it in result.checklist
        ],
        "semantic": {k: sem.get(k) for k in ("generator", "model", "status", "reason", "counts", "demoted_cards")}
        if (sem := result.verification.get("semantic")) else None,
        "timings_s": result.manifest.get("timings_s"),
        "total_s": result.manifest.get("total_s"),
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser(description="계획서 한 건 분석")
    ap.add_argument("plan", help="계획서 파일(.md/.txt)")
    ap.add_argument("--provider", choices=["openai", "mock", "off"], default=None)
    ap.add_argument("--backend", choices=["index", "fixture"], default=None)
    ap.add_argument("--corpus", help="fixture 코퍼스 JSON(--backend fixture)")
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--full", action="store_true", help="요약 대신 전체 결과 JSON")
    args = ap.parse_args(argv)
    text = Path(args.plan).read_text(encoding="utf-8")
    be = backend_mod.make_backend(args.backend, fixture_corpus=args.corpus) if args.backend else None
    result = run_premortem(text, provider=args.provider, backend=be, k=args.k)
    out = result.model_dump(mode="json") if args.full else summarize(result)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "FITNESS_MISSING",
    "MOCK_NOTICE",
    "PIPELINE_VERSION",
    "V1_DEPENDS",
    "V1_PARALLEL",
    "V1_STAGES",
    "StageCallback",
    "mask_extra_pii",
    "run_premortem",
    "safe_text",
    "summarize",
]

