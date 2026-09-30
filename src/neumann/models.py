"""Neumann 데이터 계약 (모든 에픽 공용).

이 파일은 **추가만** 한다. 기존 필드의 이름·타입·필수 여부를 바꾸려면 PM 승인과
`docs/decisions.md` 기록이 필요하다. 새 필드는 반드시 기본값을 준다(필수 필드 최소).

불변식 (생성자에서 막는다):
1. 영속 엔티티(Work·ReviewEvent·AuthorResponse·Decision·PostStatus)는 `provenance`가 필수다.
2. 신원 필드는 존재할 수 없다. 필드 이름에 신원 토큰이 있으면 클래스 정의 시점에 TypeError.
3. RiskCard는 근거(Excerpt id)가 최소 1개다. Excerpt는 원문 오프셋을 잘라 만든 글자 그대로의 구간이다.

텍스트 정규화(NFC + LF)는 자동으로 하지 않는다. 수집기는 `normalize_text()` → `redact_pii()` 순서로
원문을 만든 뒤 저장하고, 그 저장 문자열에서 `Excerpt.from_source()`로 구간을 자른다.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1"

# ── 공용 헬퍼 ────────────────────────────────────────────────────────────


def sha256_text(text: str) -> str:
    """UTF-8 문자열의 sha256 16진수."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_text(text: str) -> str:
    """저장 전 정규화: 줄바꿈을 LF로, 유니코드를 NFC로. 공백은 자르지 않는다(오프셋 보존)."""
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


# TLD를 알파벳으로 제한한다(지표 표기 `vIoU@0.3` 오탐 방지).
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
ORCID_RE = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b")


def contains_pii(text: str) -> bool:
    return bool(EMAIL_RE.search(text) or ORCID_RE.search(text))


def redact_pii(text: str) -> str:
    """이메일·ORCID를 가린다. 길이가 바뀌므로 반드시 Excerpt를 만들기 **전에** 부른다."""
    return ORCID_RE.sub("[ORCID]", EMAIL_RE.sub("[EMAIL]", text))


PSEUDONYM_RE = r"^rvw_[0-9a-f]{16}$"


def make_reviewer_pseudonym(raw_handle: str, *, scope: str, salt: str) -> str:
    """리뷰어 핸들 → `rvw_<16 hex>`. scope(논문·포럼 단위)가 다르면 값도 다르다. 빈 솔트는 거부."""
    if not salt:
        raise ValueError("pseudonym salt가 비어 있다(NEUMANN_PSEUDONYM_SALT)")
    digest = hmac.new(salt.encode("utf-8"), f"{scope}\x00{raw_handle}".encode("utf-8"), hashlib.sha256)
    return "rvw_" + digest.hexdigest()[:16]


def _check_http_url(value: str) -> str:
    if not isinstance(value, str) or not re.match(r"^https?://[^\s/$.?#][^\s]*$", value):
        raise ValueError(f"http(s) URL이 아니다: {value!r}")
    return value  # 정규화하지 않고 글자 그대로 보존한다


def _check_aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.tzinfo.utcoffset(value) is None):
        raise ValueError("timezone-aware datetime만 허용한다")
    return value


# ── 신원 필드 금지 기반 클래스 ───────────────────────────────────────────

IDENTITY_TOKENS: tuple[str, ...] = (
    "name",
    "email",
    "e_mail",
    "orcid",
    "author",
    "reviewer_id",
    "affiliation",
    "institution",
    "signature",
    "handle",
    "profile",
    "phone",
)


class NeumannModel(BaseModel):
    """모든 계약 모델의 기반. 필드 이름(과 별칭)에 신원 토큰이 있으면 클래스 정의 시점에 TypeError.

    정당한 예외는 `__identity_exempt_fields__`에 필드 이름을 명시한다.
    알 수 없는 키는 거부한다(extra="forbid") — 신원 정보가 추가 키로 새어 들어오지 못하게.
    """

    model_config = ConfigDict(extra="forbid", validate_by_name=True, validate_by_alias=True, serialize_by_alias=True)

    __identity_exempt_fields__: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        for field_name, info in cls.model_fields.items():
            if field_name in cls.__identity_exempt_fields__:
                continue
            for key in {field_name, info.alias, info.validation_alias, info.serialization_alias}:
                if not isinstance(key, str):
                    continue
                low = key.lower()
                for token in IDENTITY_TOKENS:
                    if token in low:
                        raise TypeError(
                            f"{cls.__name__}.{field_name}: 신원 필드 금지 (토큰 {token!r}, 키 {key!r})"
                        )


# ── Provenance ───────────────────────────────────────────────────────────

BLOCKED_SOURCES = frozenset({"reviewcritique"})  # 약관상 AI 개발 기여 금지


class Provenance(NeumannModel):
    """레코드의 출처. 원문 링크는 글자 그대로 보존한다(검증만)."""

    source: str = Field(min_length=1, description="소스 식별자. 예 openreview_api2, elife, europepmc")
    source_url: str = Field(description="원문 URL, 글자 그대로")
    accessed_at: datetime = Field(description="접근 시각, timezone-aware")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="받은 원문(정규화 뒤)의 sha256")
    license: str | None = None
    api_version: str | None = None

    @field_validator("source")
    @classmethod
    def _source_allowed(cls, v: str) -> str:
        if v.lower() in BLOCKED_SOURCES:
            raise ValueError(f"사용 금지 소스: {v}")
        return v

    @field_validator("source_url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _check_http_url(v)

    @field_validator("accessed_at")
    @classmethod
    def _aware_not_future(cls, v: datetime) -> datetime:
        _check_aware(v)
        if v > datetime.now(UTC) + timedelta(hours=1):
            raise ValueError("accessed_at이 미래 시각이다")
        return v


class SourcedRecord(NeumannModel):
    """영속 엔티티의 기반. provenance는 기본값 없는 필수 필드."""

    provenance: Provenance
    schema_version: str = SCHEMA_VERSION


class _HasText(SourcedRecord):
    """본문을 가진 엔티티: 본문에 이메일·ORCID가 남아 있으면 거부한다."""

    @field_validator("text", check_fields=False)
    @classmethod
    def _no_pii(cls, v: str | None) -> str | None:
        if v is not None and contains_pii(v):
            raise ValueError("본문에 이메일/ORCID가 있다. redact_pii()를 먼저 적용한다")
        return v

    @field_validator("url", check_fields=False)
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return None if v is None else _check_http_url(v)

    @property
    def text_sha256(self) -> str | None:
        text = getattr(self, "text", None)
        return None if text is None else sha256_text(text)


# ── 엔티티 ───────────────────────────────────────────────────────────────


class Work(_HasText):
    """논문·프리프린트·제출물. work_id 규약은 "{source}:{native_id}"."""

    work_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(description="사람이 열 수 있는 랜딩 페이지")
    native_id: str | None = None
    abstract: str | None = None
    doi: str | None = None
    venue: str | None = None
    year: int | None = None
    fields: list[str] = Field(default_factory=list, description="분야·키워드")
    work_type: str | None = None

    @field_validator("doi")
    @classmethod
    def _doi(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = re.sub(r"^https?://(dx\.)?doi\.org/", "", v.strip()).lower()
        if not re.match(r"^10\.\d{4,9}/\S+$", v):
            raise ValueError(f"DOI 형식이 아니다: {v!r}")
        return v


class ReviewKind(StrEnum):
    official_review = "official_review"
    public_review = "public_review"
    referee_report = "referee_report"
    meta_review = "meta_review"
    editor_assessment = "editor_assessment"
    decision_letter = "decision_letter"
    reviewer_comment = "reviewer_comment"


class ReviewEvent(_HasText):
    """심사평 한 건. `text`가 Excerpt 오프셋의 기준 문자열이다. 신원 필드는 없다."""

    review_id: str = Field(min_length=1)
    work_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    kind: ReviewKind = ReviewKind.official_review
    url: str | None = Field(default=None, description="심사평 딥링크(없으면 provenance.source_url)")
    reviewer_pseudonym: str | None = Field(default=None, pattern=PSEUDONYM_RE)
    round: int | None = Field(default=None, ge=1)
    created: datetime | None = None
    rating: str | None = Field(default=None, description="원문 그대로. 예 '5: marginally below ...'")
    confidence: str | None = None

    @field_validator("created")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        return _check_aware(v)


class AuthorResponse(_HasText):
    response_id: str = Field(min_length=1)
    work_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    review_id: str | None = Field(default=None, description="eLife처럼 전체 답변이면 None")
    url: str | None = None
    round: int | None = Field(default=None, ge=1)


class DecisionOutcome(StrEnum):
    accept_oral = "accept_oral"
    accept_spotlight = "accept_spotlight"
    accept_poster = "accept_poster"
    accept = "accept"
    major_revision = "major_revision"
    minor_revision = "minor_revision"
    reject_resubmit = "reject_resubmit"
    reject = "reject"
    desk_reject = "desk_reject"
    withdrawn = "withdrawn"
    no_binary_decision = "no_binary_decision"
    unknown = "unknown"


class Decision(_HasText):
    decision_id: str = Field(min_length=1)
    work_id: str = Field(min_length=1)
    outcome: DecisionOutcome
    outcome_raw: str = Field(min_length=1, description="소스 원문 문자열 그대로")
    text: str | None = Field(default=None, description="메타리뷰·결정서 본문")
    url: str | None = None
    mapping_rule: str | None = None


class PostStatusKind(StrEnum):
    retraction = "retraction"
    partial_retraction = "partial_retraction"
    expression_of_concern = "expression_of_concern"
    correction = "correction"
    withdrawal = "withdrawal"
    removal = "removal"
    reinstatement = "reinstatement"


class PostStatus(_HasText):
    """사후상태(철회·정정 등). 문서화된 신호만 기록한다. 비난·순위 필드는 없다."""

    post_status_id: str = Field(min_length=1)
    kind: PostStatusKind
    work_id: str | None = None
    target_doi: str | None = None
    notice_doi: str | None = None
    reason_codes: list[str] = Field(default_factory=list, description="RW 통제어휘 원문 그대로")
    text: str | None = Field(default=None, description="공지 본문(있으면)")
    url: str | None = None

    @model_validator(mode="after")
    def _target(self) -> PostStatus:
        if not (self.work_id or self.target_doi):
            raise ValueError("work_id와 target_doi 중 하나는 있어야 한다")
        return self


# ── Excerpt ──────────────────────────────────────────────────────────────

SourceKind = Literal["review", "author_response", "decision", "post_status"]


class Excerpt(NeumannModel):
    """원문 문자 오프셋 구간. `text == source_text[start:end]`가 항상 성립해야 한다.

    반드시 `Excerpt.from_source()`로 만든다(원문을 잘라서 text를 채운다).
    """

    excerpt_id: str = Field(min_length=1)
    source_kind: SourceKind
    source_id: str = Field(min_length=1, description="review_id / response_id / decision_id / post_status_id")
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_url: str
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$", description="원문 전체의 sha256")

    @field_validator("source_url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _check_http_url(v)

    @model_validator(mode="after")
    def _consistent(self) -> Excerpt:
        if self.end <= self.start:
            raise ValueError("end는 start보다 커야 한다")
        if len(self.text) != self.end - self.start:
            raise ValueError("len(text) != end - start")
        if not self.text.strip():
            raise ValueError("공백뿐인 구간")
        if sha256_text(self.text) != self.text_sha256:
            raise ValueError("text_sha256이 text와 맞지 않는다")
        return self

    @staticmethod
    def make_id(source_kind: str, source_id: str, start: int, end: int) -> str:
        return "ex_" + sha256_text(f"{source_kind}\x00{source_id}\x00{start}\x00{end}")[:16]

    @classmethod
    def from_source(
        cls,
        source_text: str,
        start: int,
        end: int,
        *,
        source_kind: SourceKind,
        source_id: str,
        source_url: str,
        excerpt_id: str | None = None,
    ) -> Excerpt:
        """원문을 잘라 Excerpt를 만든다. 범위를 벗어나면 ValueError."""
        if not (0 <= start < end <= len(source_text)):
            raise ValueError(f"오프셋 범위 오류: start={start}, end={end}, len={len(source_text)}")
        text = source_text[start:end]
        return cls(
            excerpt_id=excerpt_id or cls.make_id(source_kind, source_id, start, end),
            source_kind=source_kind,
            source_id=source_id,
            start=start,
            end=end,
            text=text,
            text_sha256=sha256_text(text),
            source_url=source_url,
            source_sha256=sha256_text(source_text),
        )

    def verify_against(self, source_text: str) -> bool:
        """원문과 글자 단위로 대조한다. 원문이 바뀌었거나 text가 조작됐으면 False."""
        if self.end > len(source_text):
            return False
        if source_text[self.start : self.end] != self.text:
            return False
        if sha256_text(self.text) != self.text_sha256:
            return False
        if self.source_sha256 is not None and sha256_text(source_text) != self.source_sha256:
            return False
        return True


# ── 위험 분류 ─────────────────────────────────────────────────────────────


class RiskCode(StrEnum):
    """최상위 위험 유형(03_risk_taxonomy). 하위 코드(R1.1 등)는 문자열로 따로 둔다."""

    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"
    R6 = "R6"
    R7 = "R7"
    R8 = "R8"
    R9 = "R9"

    @property
    def slug(self) -> str:
        return RISK_NAMES[self][0]

    @property
    def title_ko(self) -> str:
        return RISK_NAMES[self][1]

    @property
    def title_en(self) -> str:
        return RISK_NAMES[self][2]


RISK_NAMES: dict[RiskCode, tuple[str, str, str]] = {
    RiskCode.R0: ("presentation_clarity", "서술·표현", "Presentation & Clarity (non-risk sink)"),
    RiskCode.R1: ("claim_evidence", "주장-증거 정합성", "Claim-Evidence Soundness"),
    RiskCode.R2: ("evaluation_protocol", "실험 설계·평가 프로토콜", "Evaluation Protocol"),
    RiskCode.R3: ("data_leakage", "데이터 누출·분할 오염", "Data Leakage"),
    RiskCode.R4: ("data_quality", "데이터 품질·대표성", "Data Quality & Representativeness"),
    RiskCode.R5: ("reproducibility", "재현성·연구산출물", "Reproducibility & Artifacts"),
    RiskCode.R6: ("novelty_positioning", "신규성·선행연구 위치", "Novelty & Positioning"),
    RiskCode.R7: ("generalization_scope", "일반화·적용범위", "Generalization & Scope"),
    RiskCode.R8: ("domain_validation", "도메인 실증·물리적 타당성", "Domain Validation & Physical Plausibility"),
    RiskCode.R9: ("integrity_post_pub", "연구윤리·사후 위험", "Integrity & Post-publication Risk"),
}


class Generator(StrEnum):
    """결과를 누가 만들었나(정직 표기). 규칙 결과를 LLM 결과라고 쓰지 않는다."""

    astra = "astra"  # 제품 LLM gpt-6-astra
    rule = "rule"  # 규칙(비상 경로)
    mock = "mock"  # 테스트용 가짜


def _check_subcode(risk_code: RiskCode, subcode: str | None) -> None:
    if subcode is None:
        return
    if not re.match(r"^R\d(\.\d+)?$", subcode) or subcode.split(".")[0] != risk_code.value:
        raise ValueError(f"하위 코드 {subcode!r}가 {risk_code.value}에 속하지 않는다")


class RiskTag(NeumannModel):
    """발췌 하나에 붙은 위험 라벨."""

    excerpt_id: str = Field(min_length=1)
    risk_code: RiskCode
    subcode: str | None = Field(default=None, description="예 R3.2. risk_code에 속해야 한다")
    polarity: Literal["negative", "positive", "neutral"] = "negative"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    generator: Generator
    model: str | None = Field(default=None, description="LLM이면 모델 id")

    @model_validator(mode="after")
    def _sub(self) -> RiskTag:
        _check_subcode(self.risk_code, self.subcode)
        return self


class WhyApplies(NeumannModel):
    """이 위험이 왜 이 계획서에 해당하는가. 계획서 줄 번호(1부터)로 근거를 댄다."""

    text: str = Field(min_length=1)
    plan_lines: list[int] = Field(default_factory=list)

    @field_validator("plan_lines")
    @classmethod
    def _positive(cls, v: list[int]) -> list[int]:
        if any(n < 1 for n in v):
            raise ValueError("계획서 줄 번호는 1부터다")
        return v


class RiskScore(NeumannModel):
    """점수 구성요소. 모두 0~1. total 계산식은 E3가 정하고 weights에 함께 남긴다."""

    similarity: float = Field(ge=0.0, le=1.0)
    frequency: float = Field(ge=0.0, le=1.0)
    severity: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    total: float = Field(ge=0.0, le=1.0)
    weights: dict[str, float] = Field(default_factory=dict)


class RiskCard(NeumannModel):
    """위험카드. 근거(Excerpt id)가 최소 1개 없으면 만들 수 없다."""

    card_id: str = Field(min_length=1)
    risk_code: RiskCode
    title: str = Field(min_length=1)
    why_applies: WhyApplies
    evidence: list[str] = Field(min_length=1, description="Excerpt id 목록(최소 1)")
    score: RiskScore
    generator: Generator
    works: list[str] = Field(default_factory=list, description="근거 논문 work_id 목록")
    subcode: str | None = None
    model: str | None = None

    @field_validator("evidence")
    @classmethod
    def _ids(cls, v: list[str]) -> list[str]:
        if any(not (isinstance(x, str) and x.strip()) for x in v):
            raise ValueError("빈 excerpt id")
        return v

    @model_validator(mode="after")
    def _sub(self) -> RiskCard:
        _check_subcode(self.risk_code, self.subcode)
        return self


# ── 실행 기록 ─────────────────────────────────────────────────────────────

StageState = Literal["ok", "degraded", "skipped", "error"]


class StageStatus(NeumannModel):
    """단계 하나의 실행 기록(강등 기록용).

    파이썬 이름은 stage/state/detail, JSON 키는 계약(StageReport)대로 name/status/reason이다.
    어느 쪽 이름으로도 만들 수 있다.
    """

    __identity_exempt_fields__: ClassVar[frozenset[str]] = frozenset({"stage"})  # JSON 키 "name"은 단계 이름

    stage: str = Field(min_length=1, alias="name")
    state: StageState = Field(default="ok", alias="status")
    detail: str | None = Field(default=None, alias="reason")
    phase: str = "pipeline"
    impl: str | None = Field(default=None, description="실제 호출된 module:attr 또는 fallback:*")
    elapsed_s: float = 0.0
    counts: dict[str, int] = Field(default_factory=dict)


# ── 계획서 ────────────────────────────────────────────────────────────────


class PlanLine(NeumannModel):
    no: int = Field(ge=1)
    text: str


class PlanDocument(NeumannModel):
    """업로드된 계획서. plan_id = sha256(본문). 본문은 세션 안에서만 쓰고 영속 저장하지 않는다."""

    plan_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_id: str = Field(min_length=1)
    lines: list[PlanLine]

    @model_validator(mode="after")
    def _check(self) -> PlanDocument:
        if [ln.no for ln in self.lines] != list(range(1, len(self.lines) + 1)):
            raise ValueError("줄 번호는 1부터 연속이어야 한다")
        if sha256_text(self.text) != self.plan_id:
            raise ValueError("plan_id가 본문 sha256과 맞지 않는다")
        return self

    @classmethod
    def from_text(cls, text: str, session_id: str, *, redact: bool = True) -> PlanDocument:
        """정규화(NFC+LF) → (기본) 이메일·ORCID 가림 → 줄 번호 부여."""
        body = normalize_text(text)
        if redact:
            body = redact_pii(body)
        lines = [PlanLine(no=i, text=t) for i, t in enumerate(body.split("\n"), start=1)]
        return cls(plan_id=sha256_text(body), session_id=session_id, lines=lines)

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)

    def line(self, no: int) -> str:
        return self.lines[no - 1].text

    def dump_persisted(self) -> dict[str, Any]:
        """영속 저장용 dump. 본문(줄 텍스트)은 빼고 식별자·줄 수만 남긴다."""
        return {"plan_id": self.plan_id, "session_id": self.session_id, "n_lines": len(self.lines)}


# ── 결과 ──────────────────────────────────────────────────────────────────


class SimilarWork(NeumannModel):
    work_id: str = Field(min_length=1)
    similarity: float = Field(ge=-1.0, le=1.0)
    title: str | None = None
    url: str | None = None
    venue: str | None = None
    year: int | None = None
    axis_scores: dict[str, float] = Field(default_factory=dict, description="method/data/evaluation 축별 유사도")


class PremortemResult(NeumannModel):
    """`run_premortem`의 반환형. `model_dump(mode="json")`이 contracts/premortem_response.schema.json을 통과한다.

    필수는 session_id·plan_id뿐. 나머지 필드는 계약 스키마의 키와 이름이 같다.
    - 위험카드: `risk_cards`, 단계 기록: `stages`(StageStatus), 근거 구간: `evidence`(Excerpt)
    - 카드가 인용한 excerpt id는 모두 `evidence`에 있어야 한다.
    - 단계 중 degraded/error가 있으면 status는 자동으로 "degraded"가 된다(ok로 숨기지 않는다).
    """

    session_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: Literal["ok", "degraded", "error"] = "ok"
    pipeline_version: str = "neumann-" + SCHEMA_VERSION
    plan: PlanDocument | None = None
    similar_works: list[SimilarWork] = Field(default_factory=list)
    evidence: list[Excerpt] = Field(default_factory=list)
    risk_cards: list[RiskCard] = Field(default_factory=list)
    stages: list[StageStatus] = Field(default_factory=list)
    expected_review: dict[str, Any] = Field(default_factory=dict)
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)
    # 아래는 계약 스키마에 있는 자유 형식 칸. 쓰지 않으면 비워 둔다.
    plan_stats: dict[str, Any] = Field(default_factory=dict)
    axes: dict[str, str] = Field(default_factory=dict)
    domain: str | None = None
    claims: list[str] = Field(default_factory=list)
    post_status: list[dict[str, Any]] = Field(default_factory=list)
    field_prior: dict[str, Any] | None = None
    plan_checks: dict[str, Any] = Field(default_factory=dict)
    research_questions: dict[str, Any] = Field(default_factory=dict)
    plan_side_candidates: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    risk_synthesis: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] = Field(default_factory=dict)

    @field_validator("generated_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return _check_aware(v)  # type: ignore[return-value]

    @model_validator(mode="after")
    def _invariants(self) -> PremortemResult:
        if self.plan is not None and self.plan.plan_id != self.plan_id:
            raise ValueError("plan.plan_id와 plan_id가 다르다")
        known = {ex.excerpt_id for ex in self.evidence}
        for card in self.risk_cards:
            missing = [x for x in card.evidence if x not in known]
            if missing:
                raise ValueError(f"카드 {card.card_id}의 근거 {missing}가 evidence에 없다")
        if self.status == "ok" and any(s.state in ("degraded", "error") for s in self.stages):
            self.status = "degraded"
        return self

    def dump_persisted(self) -> dict[str, Any]:
        """영속 저장용 dump. 계획서 본문을 빼고 plan_id·줄 수만 남긴다."""
        data = self.model_dump(mode="json", exclude={"plan"})
        if self.plan is not None:
            data["plan"] = self.plan.dump_persisted()
        return data


__all__ = [
    "SCHEMA_VERSION",
    "AuthorResponse",
    "Decision",
    "DecisionOutcome",
    "Excerpt",
    "Generator",
    "NeumannModel",
    "PlanDocument",
    "PlanLine",
    "PostStatus",
    "PostStatusKind",
    "PremortemResult",
    "Provenance",
    "ReviewEvent",
    "ReviewKind",
    "RISK_NAMES",
    "RiskCard",
    "RiskCode",
    "RiskScore",
    "RiskTag",
    "SimilarWork",
    "SourceKind",
    "SourcedRecord",
    "StageState",
    "StageStatus",
    "WhyApplies",
    "Work",
    "contains_pii",
    "make_reviewer_pseudonym",
    "normalize_text",
    "redact_pii",
    "sha256_text",
]
