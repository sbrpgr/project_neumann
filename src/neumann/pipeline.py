"""분석 파이프라인: 계획서 → 적합성 → 유사 연구 → astra 지적 추출 → astra 카드 합성 → 원문 대조
→ 예상 심사평 → 예방 체크리스트 → 2차 의미검증.

    run_premortem(plan_text, *, session_id=None) -> PremortemResult

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

명령줄: python -m neumann.pipeline PLAN.md [--provider openai|mock|off] [--backend index|fixture --corpus X.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import traceback
import uuid
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


@dataclass
class _Run:
    stages: list[StageStatus] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def stage(self, name: str, phase: str):
        rec: dict[str, Any] = {"state": "ok", "detail": None, "impl": None, "counts": {}}
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

    def fill(self, rec: dict[str, Any], stage: StageStatus) -> None:
        """모듈이 만든 단계 기록(StageStatus)을 이 단계의 기록으로 옮긴다(소요 시간은 여기서 잰다)."""
        rec.update(state=stage.state, detail=stage.detail, impl=stage.impl, counts=dict(stage.counts))

    def skip(self, name: str, phase: str, why: str) -> None:
        self.stages.append(StageStatus(stage=name, state="skipped", detail=safe_text(why), phase=phase))
        self.timings[name] = 0.0

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
) -> PremortemResult:
    """계획서 한 건을 분석한다. 예외로 죽지 않고 강등을 기록한다.

    llm/provider: 주입한 provider가 우선, 없으면 provider 이름("openai"|"mock"|"off"), 없으면 설정.
    backend: 근거 저장소. 없으면 E2 실색인(`IndexBackend`). fixture는 명시할 때만.
    exclude_work_ids: 백테스트 누출 제거용(검색에서 뺀다).
    cache_dir: 캐시 뿌리(기본 `data/cache`, None이면 캐시 끔). 추출은 `extract/`, 검색어는 `queries/`.
    """
    t_start = time.perf_counter()
    run = _Run()
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
            if fit.get("notice"):
                run.notice(fit["notice"])
            if not fit.get("analyze", True):
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
            hits = backend.search(search_queries, k=k, exclude_work_ids=exclude_work_ids)
            top = max((h.score for h in hits), default=None)
            kept = [h for h in hits if h.score >= min_similarity]
            st["counts"] = {"hits": len(hits), "kept": len(kept), "queries": len(search_queries)}
            st["detail"] = f"상위 점수 {top:.3f}" if top is not None else "검색 결과 0건"
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
    if qp is not None and not qp.is_research and fit_verdict in (None, "uncertain"):
        search_info = extras["plan_checks"].get("search", {})
        top = search_info.get("top_score")
        score_s = (
            f"유사 연구 검색 상위 점수 {top:.3f}" if isinstance(top, float)
            else ("유사 연구 검색 결과 0건" if "search" in extras["plan_checks"] else "검색 안 함")
        )
        no_card_reason = f"입력이 연구계획서가 아니다({qp.generator} 판단: {qp.reason}); {score_s}"
        if fit_verdict == "uncertain":
            no_card_reason += f"; 적합성 판정 보류({fit.get('generator') if fit else '-'})"

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
            synthesis = cards_mod.synthesize_cards(
                plan, extraction.issues, titles, similarity, len(extraction.works_analyzed), llm, settings
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
        return PremortemResult(
            session_id=session_id, plan_id=plan.plan_id, status="error", stages=stages,
            notices=[*run.notices, "결과 조립 실패"], manifest=manifest,
            risk_synthesis={"no_card_reason": "결과 조립 실패"},
        )

    # 8~10. 예상 심사평 → 체크리스트 → 2차 검증(카드가 없으면 각 모듈이 호출 없이 skipped로 남긴다) ────────
    result = _attach_v1(result, plan, llm, settings, stage_limits)
    manifest = {
        **result.manifest,
        "timings_s": {s.stage: s.elapsed_s for s in result.stages},
        "total_s": round(time.perf_counter() - t_start, 3),
        "stage_limits_s": stage_limits,
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


def _attach_v1(
    result: PremortemResult, plan: PlanDocument, llm: LLMProvider, settings: Any, stage_limits: dict[str, float]
) -> PremortemResult:
    """예상 심사평(E3-L1a) → 체크리스트 → 2차 검증(E3-L1b)을 차례로 붙인다.

    단계마다 따로 막는다: 한 단계가 예외로 죽으면 그 단계만 error로 남기고 앞 결과를 그대로 넘긴다.
    모듈이 LLM 실패로 규칙 경로·미검증으로 물러나면 그 단계만 degraded(모듈의 단계 기록)다.
    화면 단계 묶음(phase)은 파이프라인 기준(REVIEW·ACTION)으로 맞추고, 강등이면 notices에 한 줄 남긴다.
    """
    for task, phase in V1_STAGES:
        t0 = time.perf_counter()
        call, opts, why = _llm_call_for(llm, task, settings)
        stage_limits[task] = opts["timeout_s"]
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
            result = checklist_mod.with_stage(result, stage, notices=notices)
            continue
        # 모듈이 'llm_failed'처럼 분류만 남기면 어댑터가 받은 실패 사유(시간 초과 등, 비밀값 없음)를 덧붙인다
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
        result = new.model_copy(update={"stages": stages})
    return result


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
    "V1_STAGES",
    "mask_extra_pii",
    "run_premortem",
    "safe_text",
    "summarize",
]

