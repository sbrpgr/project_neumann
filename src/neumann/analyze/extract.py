"""astra ② 심사평 지적 추출(02_LLM_호출_명세 EX-4 출력 계약).

- 입력: 논문 하나의 심사평 문장(Excerpt) 묶음. 호출 안에서는 짧은 별칭(s1, s2 …)으로 보내고 코드가 excerpt_id로 되돌린다.
- 출력: 발췌마다 0개 이상의 지적 {excerpt_id(입력 enum), start, end(발췌 안 위치, 둘 다 null이면 문장 전체),
  risk_code(R0~R9 enum), polarity, confidence}. **인용문 필드가 없다.** 인용은 코드가 원문을 잘라 만든다.
- 검증: 범위 밖·빈 구간·한쪽만 있는 위치·enum 밖·R9(심사평에서 추론 금지)·신뢰도 범위 밖은 버리고 사유별로 센다.
  남긴 위치는 단어 경계로 넓힌다(원문 구간 그대로, 넓힌 수를 센다).
- 논문 단위(길면 묶음 단위)로 병렬 호출하고, 성공한 응답은 심사평 해시로 `data/cache/extract/`에 캐시한다.
- 실패·시간 초과한 묶음만 규칙 태그로 대신한다(generator="rule").
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from neumann.analyze.risk_brief import TAXONOMY_BRIEF
from neumann.analyze.rules import RuleTagger
from neumann.llm import LLMCall, LLMProvider, LLMResult, task_options
from neumann.models import Excerpt, RiskCode, RiskTag, sha256_text

log = logging.getLogger(__name__)

TASK = "extract_issues"
PROMPT_VERSION = "extract_issues.v1"
POLARITIES = ("negative", "positive", "neutral")
DEFAULT_BATCH = 40
DEFAULT_PARALLEL = 10

INSTRUCTIONS = f"""\
You label sentences from peer reviews of ONE scientific paper with research-risk types.
Input: the paper title and the reviewers' sentences, each with an id.

For every sentence that states a weakness, concern, doubt, missing element, or a request for additional work or
information about the research, output an issue with polarity "negative" and the single best risk_code.
If one sentence raises two or more distinct concerns, output one issue per concern.
Explicit praise of a risk-relevant aspect (e.g. "the baselines are strong") may be output with polarity "positive".
Skip sentences that only summarise the paper, headings, greetings, scores, and neutral questions that imply no gap.

Offsets: start and end are 0-based character offsets inside that sentence's text (end exclusive).
Use null for both unless the sentence contains several distinct concerns; then give the span of each concern.
You never return quoted text; the system cuts quotes from the source itself.
confidence is your probability (0 to 1) that the risk_code is correct.
Never use R9. Use R0 for presentation-only remarks.

{TAXONOMY_BRIEF}"""


def build_schema(ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "excerpt_id": {"type": "string", "enum": ids},
                        "start": {"type": ["integer", "null"]},
                        "end": {"type": ["integer", "null"]},
                        "risk_code": {"type": "string", "enum": [c.value for c in RiskCode]},
                        "polarity": {"type": "string", "enum": list(POLARITIES)},
                        "confidence": {"type": "number"},
                    },
                    "required": ["excerpt_id", "start", "end", "risk_code", "polarity", "confidence"],
                },
            }
        },
        "required": ["issues"],
    }


@dataclass
class Issue:
    """검증을 통과한 지적 하나. 인용은 excerpt.text[rel_start:rel_end](원문 구간)이다."""

    excerpt: Excerpt
    work_id: str
    risk_code: RiskCode
    polarity: str
    confidence: float
    rel_start: int
    rel_end: int
    generator: str  # astra | mock | rule
    model: str | None = None

    @property
    def quote(self) -> str:
        return self.excerpt.text[self.rel_start : self.rel_end]

    @property
    def whole_sentence(self) -> bool:
        return self.rel_start == 0 and self.rel_end == len(self.excerpt.text)

    def evidence_excerpt(self) -> Excerpt:
        """카드 근거로 쓸 Excerpt. 문장 전체면 원래 발췌, 일부면 같은 원문의 하위 구간(오프셋 절대값)."""
        if self.whole_sentence:
            return self.excerpt
        ex = self.excerpt
        start, end = ex.start + self.rel_start, ex.start + self.rel_end
        text = self.quote
        return Excerpt(
            excerpt_id=Excerpt.make_id(ex.source_kind, ex.source_id, start, end),
            source_kind=ex.source_kind,
            source_id=ex.source_id,
            start=start,
            end=end,
            text=text,
            text_sha256=sha256_text(text),
            source_url=ex.source_url,
            source_sha256=ex.source_sha256,
        )

    def tag(self) -> RiskTag:
        return RiskTag(
            excerpt_id=self.evidence_excerpt().excerpt_id,
            risk_code=self.risk_code,
            polarity=self.polarity,  # type: ignore[arg-type]
            confidence=self.confidence,
            generator=self.generator,  # type: ignore[arg-type]
            model=self.model,
        )


@dataclass
class BatchOutcome:
    work_id: str
    n_excerpts: int
    issues: list[Issue]
    generator: str
    llm: LLMResult | None = None
    cached: bool = False
    fallback_reason: str | None = None
    n_raw: int = 0
    drops: Counter = field(default_factory=Counter)
    snapped: int = 0
    latency_s: float = 0.0


@dataclass
class ExtractionResult:
    issues: list[Issue]
    batches: list[BatchOutcome]
    works_analyzed: list[str]

    @property
    def n_raw(self) -> int:
        return sum(b.n_raw for b in self.batches)

    @property
    def drops(self) -> Counter:
        total: Counter = Counter()
        for b in self.batches:
            total.update(b.drops)
        return total

    @property
    def fallback_batches(self) -> list[BatchOutcome]:
        return [b for b in self.batches if b.fallback_reason]

    def counts(self) -> dict[str, int]:
        """단계 기록용 수치. findings_* 는 LLM(astra·mock·캐시)이 돌려준 지적 기준이다(규칙 대체분은 findings_rule)."""
        c = {
            "works": len(self.works_analyzed),
            "batches": len(self.batches),
            "batches_llm": sum(1 for b in self.batches if not b.fallback_reason),
            "batches_cached": sum(1 for b in self.batches if b.cached),
            "batches_rule": len(self.fallback_batches),
            "excerpts": sum(b.n_excerpts for b in self.batches),
            "findings_total": self.n_raw,
            "findings_kept": sum(len(b.issues) for b in self.batches if not b.fallback_reason),
            "findings_dropped": sum(self.drops.values()),
            "findings_rule": sum(len(b.issues) for b in self.fallback_batches),
            "spans_snapped": sum(b.snapped for b in self.batches),
        }
        for reason, n in sorted(self.drops.items()):
            c[f"drop_{reason}"] = n
        return c

    def llm_results(self) -> list[LLMResult]:
        return [b.llm for b in self.batches if b.llm is not None]

    def drop_rate(self) -> float | None:
        return None if not self.n_raw else sum(self.drops.values()) / self.n_raw


# ── 검증 ─────────────────────────────────────────────────────────────────


def _snap(text: str, s: int, e: int) -> tuple[int, int]:
    """단어 중간에서 잘린 구간을 단어 경계까지 넓히고 앞뒤 공백을 걷는다(원문 구간은 그대로 원문)."""
    while s > 0 and text[s - 1].isalnum() and text[s].isalnum():
        s -= 1
    while e < len(text) and text[e - 1].isalnum() and text[e].isalnum():
        e += 1
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def validate_issues(
    raw_issues: list[dict[str, Any]],
    by_id: dict[str, Excerpt],
    work_id: str,
    *,
    generator: str,
    model: str | None,
) -> tuple[list[Issue], Counter, int]:
    """모델이 돌려준 지적을 검증한다. (남긴 지적, 폐기 사유 집계, 넓힌 구간 수)."""
    kept: list[Issue] = []
    drops: Counter = Counter()
    snapped = 0
    seen: set[tuple[str, str, int, int]] = set()
    codes = {c.value for c in RiskCode}
    for item in raw_issues:
        ex = by_id.get(str(item.get("excerpt_id")))
        if ex is None:
            drops["unknown_excerpt_id"] += 1
            continue
        code = item.get("risk_code")
        if code not in codes:
            drops["bad_enum_risk_code"] += 1
            continue
        if code == RiskCode.R9.value:
            drops["r9_from_review"] += 1
            continue
        pol = item.get("polarity")
        if pol not in POLARITIES:
            drops["bad_enum_polarity"] += 1
            continue
        conf = item.get("confidence")
        if not isinstance(conf, int | float) or isinstance(conf, bool) or not (0.0 <= float(conf) <= 1.0):
            drops["bad_confidence"] += 1
            continue
        s, e = item.get("start"), item.get("end")
        n = len(ex.text)
        if s is None and e is None:
            s, e = 0, n
        elif s is None or e is None:
            drops["half_span"] += 1
            continue
        elif not (isinstance(s, int) and isinstance(e, int)) or isinstance(s, bool) or isinstance(e, bool):
            drops["bad_span_type"] += 1
            continue
        elif s < 0 or e > n or s >= e:
            drops["out_of_range"] += 1
            continue
        if not ex.text[s:e].strip():
            drops["empty_span"] += 1
            continue
        s2, e2 = _snap(ex.text, s, e)
        if (s2, e2) != (s, e):
            snapped += 1
        key = (ex.excerpt_id, code, s2, e2)
        if key in seen:
            drops["duplicate"] += 1
            continue
        seen.add(key)
        kept.append(
            Issue(
                excerpt=ex, work_id=work_id, risk_code=RiskCode(code), polarity=pol, confidence=float(conf),
                rel_start=s2, rel_end=e2, generator=generator, model=model,
            )
        )
    return kept, drops, snapped


def rule_issues(excerpts: list[Excerpt], work_id: str, tagger: RuleTagger) -> list[Issue]:
    """비상 경로: 규칙 태그를 Issue로(문장 전체 구간, generator="rule"). R9는 심사평에서 만들지 않는다."""
    out: list[Issue] = []
    for ex, code, pol, conf in tagger(excerpts):
        if code == RiskCode.R9:
            continue
        out.append(
            Issue(excerpt=ex, work_id=work_id, risk_code=code, polarity=pol, confidence=conf,
                  rel_start=0, rel_end=len(ex.text), generator="rule")
        )
    return out


# ── 캐시 ─────────────────────────────────────────────────────────────────


def cache_key(model: str, effort: str | None, excerpts: list[Excerpt]) -> str:
    """심사평 문장 해시 기반 키. 같은 문장 묶음·모델·지시문 판이면 같은 키."""
    body = json.dumps(
        {"v": PROMPT_VERSION, "model": model, "effort": effort, "items": [[ex.excerpt_id, ex.text_sha256] for ex in excerpts]},
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _cache_read(cache_dir: Path | None, key: str) -> list[dict[str, Any]] | None:
    if cache_dir is None:
        return None
    path = cache_dir / f"{key}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    issues = data.get("issues")
    return issues if isinstance(issues, list) else None


def _cache_write(cache_dir: Path | None, key: str, issues: list[dict[str, Any]], model: str) -> None:
    if cache_dir is None:
        return
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = cache_dir / f"{key}.tmp"
        tmp.write_text(json.dumps({"v": PROMPT_VERSION, "model": model, "issues": issues}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache_dir / f"{key}.json")
    except OSError as exc:
        log.warning("추출 캐시 쓰기 실패: %s", type(exc).__name__)


# ── 호출 ─────────────────────────────────────────────────────────────────


def _batches(excerpts: list[Excerpt], size: int) -> list[list[Excerpt]]:
    return [excerpts[i : i + size] for i in range(0, len(excerpts), size)] or []


def _run_batch(
    work_id: str,
    title: str | None,
    batch: list[Excerpt],
    llm: LLMProvider,
    opts: dict[str, Any],
    cache_dir: Path | None,
    tagger: RuleTagger,
) -> BatchOutcome:
    t0 = time.perf_counter()
    alias = {f"s{i + 1}": ex for i, ex in enumerate(batch)}
    real = {ex.excerpt_id: ex for ex in batch}
    use_cache = llm.name == "openai"
    key = cache_key(llm.model, opts["effort"], batch)
    if use_cache:
        cached = _cache_read(cache_dir, key)
        if cached is not None:
            issues, drops, snapped = validate_issues(cached, real, work_id, generator="astra", model=llm.model)
            return BatchOutcome(work_id, len(batch), issues, "astra", cached=True, n_raw=len(cached), drops=drops,
                                snapped=snapped, latency_s=time.perf_counter() - t0)
    call = LLMCall(
        task=TASK,
        instructions=INSTRUCTIONS,
        payload={"paper_title": title or "", "sentences": [{"id": a, "text": ex.text} for a, ex in alias.items()]},
        schema=build_schema(list(alias)),
        schema_name="review_issues",
        effort=opts["effort"],
        timeout_s=opts["timeout_s"],
        max_output_tokens=16000,
    )
    res = llm.complete_json(call)
    if not res.ok or res.data is None:
        return BatchOutcome(work_id, len(batch), rule_issues(batch, work_id, tagger), "rule", llm=res,
                            fallback_reason=res.reason(), latency_s=time.perf_counter() - t0)
    raw = res.data.get("issues", [])
    # 별칭 → 실제 excerpt_id. 모르는 별칭은 그대로 두어 unknown_excerpt_id로 버려지게 한다.
    mapped = [{**it, "excerpt_id": alias[it["excerpt_id"]].excerpt_id if it.get("excerpt_id") in alias else f"?{it.get('excerpt_id')}"}
              for it in raw]
    issues, drops, snapped = validate_issues(mapped, real, work_id, generator=res.generator, model=res.model)
    if use_cache:
        _cache_write(cache_dir, key, mapped, llm.model)
    return BatchOutcome(work_id, len(batch), issues, res.generator, llm=res, n_raw=len(raw), drops=drops,
                        snapped=snapped, latency_s=time.perf_counter() - t0)


def extract_issues(
    works: list[tuple[str, str | None, list[Excerpt]]],
    llm: LLMProvider,
    *,
    tagger: RuleTagger,
    settings: Any = None,
    cache_dir: Path | None = None,
    batch_size: int = DEFAULT_BATCH,
    parallel: int = DEFAULT_PARALLEL,
    stage_timeout_s: float | None = None,
) -> ExtractionResult:
    """works: (work_id, 제목, 심사평 문장 목록). 묶음을 병렬로 부르고, 단계 상한을 넘긴 묶음은 규칙으로 대신한다."""
    opts = task_options(TASK, settings)
    jobs: list[tuple[str, str | None, list[Excerpt]]] = []
    for work_id, title, excerpts in works:
        for batch in _batches(excerpts, max(1, batch_size)):
            jobs.append((work_id, title, batch))
    deadline = stage_timeout_s if stage_timeout_s is not None else opts["timeout_s"] + 30.0
    outcomes: list[BatchOutcome | None] = [None] * len(jobs)
    if jobs:
        pool = ThreadPoolExecutor(max_workers=max(1, min(parallel, len(jobs))), thread_name_prefix="extract")
        futures = {pool.submit(_run_batch, w, t, b, llm, opts, cache_dir, tagger): i for i, (w, t, b) in enumerate(jobs)}
        done, _ = wait(futures, timeout=deadline)
        for fut, i in futures.items():
            work_id, _title, batch = jobs[i]
            if fut in done:
                try:
                    outcomes[i] = fut.result()
                    continue
                except Exception as exc:  # noqa: BLE001
                    why = f"묶음 처리 오류 {type(exc).__name__}"
            else:
                why = f"단계 상한 {deadline:.0f}s 초과"
            outcomes[i] = BatchOutcome(work_id, len(batch), rule_issues(batch, work_id, tagger), "rule", fallback_reason=why)
        pool.shutdown(wait=False, cancel_futures=True)
    batches = [o for o in outcomes if o is not None]
    issues = [iss for b in batches for iss in b.issues]
    return ExtractionResult(issues=issues, batches=batches, works_analyzed=[w for w, _, ex in works if ex])
