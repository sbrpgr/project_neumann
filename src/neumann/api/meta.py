"""메타 API(E4-L1d): 코퍼스·색인 실측 메타, 위험 택소노미, 위험점수 공식.

    from neumann.api.meta import router
    app.include_router(router)      # GET /api · GET /taxonomy · GET /config/weights

- ``GET /api``: 공유 데이터 폴더의 매니페스트 두 개(``processed/corpus_manifest.json``,
  ``index/manifest.json``)에서 코퍼스 편수·분야별 수·심사평 수·거절 비율·색인 문장(발췌) 수·빌드 시각을
  읽어 그대로 돌려준다. 숫자는 매니페스트 값만 쓴다(여기서 다시 세거나 지어내지 않는다).
  매니페스트나 필드가 없으면 값은 ``null``이고 사유를 ``reasons``에 적는다. 응답은 항상 200이다.
  로컬 절대 경로·GPU 이름 같은 환경 정보는 내보내지 않는다(공개 서버에서도 쓴다).
- ``GET /taxonomy``: R0~R9 이름·설명·심각도 기본값. 기준은 기획서 ``부록/설계/03_risk_taxonomy.md``
  (v1.0, §2.3 심각도 표, §3 Tier-1 카드). 이름은 ``neumann.models.RISK_NAMES``와 같은 값을 쓴다.
- ``GET /config/weights``: 위험점수 공식. PM 결정(docs/decisions.md 2026-09-30 19:15)대로
  **유사도 × 빈도 × 심각도 × 신뢰도의 곱, 가중치 없음**(``weights=null``, ``weighted=false``)을 보이고 결정 출처를 적는다.
  설계·목업의 0.3/0.3/0.3/0.1은 ``legacy_design_weights``에 "제품에서 쓰지 않는 옛 설계값"으로만 남긴다.
  파이프라인 점수 모듈(``neumann.analyze.cards``)이 있으면 그 모듈의 공식·가중치가 곱(가중치 전부 1.0)과
  같은지(``pipeline.matches``) 대조한다.
"""

from __future__ import annotations

import copy
import importlib
import json
import logging
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

import neumann
from neumann.config import get_settings
from neumann.models import RISK_NAMES, SCHEMA_VERSION, RiskCode

log = logging.getLogger("neumann.api.meta")

router = APIRouter(tags=["meta"])

CORPUS_MANIFEST = "processed/corpus_manifest.json"
INDEX_MANIFEST = "index/manifest.json"

# ───────────────────────── 의존성(테스트에서 덮어쓴다) ─────────────────────────


def get_data_dir() -> Path:
    """공유 데이터 폴더(설정 ``NEUMANN_DATA_DIR``)."""
    return Path(get_settings().data_dir)


PIPELINE_SCORE_MODULE = "neumann.analyze.cards"


def get_pipeline_scoring() -> dict[str, Any]:
    return pipeline_scoring(PIPELINE_SCORE_MODULE)


# ───────────────────────── 매니페스트 읽기 ─────────────────────────


def read_manifest(data_dir: Path, rel: str) -> tuple[dict[str, Any] | None, str]:
    """(내용, 사유). 없거나 깨졌으면 (None, 사유). 사유에는 상대 경로와 예외 종류만 넣는다."""
    path = Path(data_dir) / rel
    if not path.is_file():
        return None, f"매니페스트 없음: {rel}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"매니페스트 읽기 실패: {rel} ({type(exc).__name__})"
    if not isinstance(data, dict):
        return None, f"매니페스트 형식 오류: {rel} (최상위가 객체가 아니다)"
    return data, ""


_KINDS: dict[str, tuple[type, ...]] = {
    "int": (int,),
    "num": (int, float),
    "str": (str,),
    "bool": (bool,),
    "dict": (dict,),
    "list": (list,),
}


class _Picker:
    """매니페스트에서 필드를 꺼낸다. 없거나 형식이 틀리면 None을 돌려주고 경로를 기록한다."""

    def __init__(self, data: Mapping[str, Any] | None, rel: str) -> None:
        self.data = data
        self.rel = rel
        self.missing: list[str] = []

    def get(self, path: tuple[str, ...], kind: str) -> Any:
        if self.data is None:
            return None
        cur: Any = self.data
        for key in path:
            if not isinstance(cur, Mapping) or key not in cur:
                self.missing.append("/".join(path))
                return None
            cur = cur[key]
        ok = isinstance(cur, _KINDS[kind]) and not (kind in ("int", "num") and isinstance(cur, bool))
        if ok and kind == "num" and not math.isfinite(float(cur)):
            ok = False
        if not ok:
            self.missing.append("/".join(path) + " (형식 오류)")
            return None
        return cur

    def reason(self) -> str:
        return f"필드 없음: {self.rel} → " + ", ".join(self.missing) if self.missing else ""


def _corpus_section(data: dict[str, Any] | None, reason: str) -> tuple[dict[str, Any], list[str]]:
    p = _Picker(data, CORPUS_MANIFEST)
    section: dict[str, Any] = {
        "available": data is not None,
        "manifest": CORPUS_MANIFEST,
        "source": p.get(("source",), "str"),
        "venues": p.get(("population", "venues"), "list"),
        "license": p.get(("license",), "str"),
        "attribution": p.get(("attribution",), "str"),
        "generated_at": p.get(("generated_at",), "str"),
        "works": p.get(("selection", "works"), "int"),
        "by_field": p.get(("selection", "by_field"), "dict"),
        "by_field_ko": p.get(("selection", "by_field_ko"), "dict"),
        "multi_field_works": p.get(("selection", "multi_field_works"), "int"),
        "by_venue": p.get(("selection", "by_venue"), "dict"),
        "reviews": p.get(("outputs", "reviews.jsonl", "records"), "int"),
        "official_reviews": p.get(("linking", "official_reviews"), "int"),
        "meta_reviews": p.get(("linking", "meta_reviews"), "int"),
        "works_with_reviews": p.get(("linking", "works_with_official_review"), "int"),
        "author_responses": p.get(("outputs", "author_responses.jsonl", "records"), "int"),
        "decisions": {
            "accept": p.get(("decisions", "accept"), "int"),
            "reject": p.get(("decisions", "reject"), "int"),
            "unknown": p.get(("decisions", "unknown"), "int"),
            "reject_ratio": p.get(("decisions", "reject_ratio"), "num"),
            "distribution": p.get(("decisions", "distribution"), "dict"),
        },
    }
    reasons = [r for r in (reason, p.reason()) if r]
    section["reason"] = "; ".join(reasons)
    return section, reasons


def _index_section(data: dict[str, Any] | None, reason: str) -> tuple[dict[str, Any], list[str]]:
    p = _Picker(data, INDEX_MANIFEST)
    section: dict[str, Any] = {
        "available": data is not None,
        "manifest": INDEX_MANIFEST,
        "format": p.get(("format",), "str"),
        "built_at": p.get(("built_at",), "str"),
        "works": p.get(("counts", "works"), "int"),
        "reviews": p.get(("counts", "reviews"), "int"),
        "excerpts": p.get(("counts", "excerpts"), "int"),
        "tags": p.get(("counts", "tags"), "int"),
        "tag_counts": p.get(("counts", "tag_counts"), "dict"),
        "dense_model": p.get(("dense_model",), "str"),
        "lexical": p.get(("backend", "lexical"), "str"),
        "degraded": p.get(("backend", "degraded"), "bool"),
        "offset_check": {
            "checked": p.get(("offset_check", "checked"), "int"),
            "passed": p.get(("offset_check", "passed"), "int"),
            "failed": p.get(("offset_check", "failed"), "int"),
            "rate": p.get(("offset_check", "rate"), "num"),
        },
    }
    # degraded_reason은 정상일 때 null이 정상값이라 필수 필드로 보지 않는다.
    backend = data.get("backend") if isinstance(data, dict) else None
    dr = backend.get("degraded_reason") if isinstance(backend, dict) else None
    section["degraded_reason"] = dr if isinstance(dr, str) else None
    reasons = [r for r in (reason, p.reason()) if r]
    section["reason"] = "; ".join(reasons)
    return section, reasons


def _index_matches_corpus(corpus: dict[str, Any] | None, index: dict[str, Any] | None) -> tuple[bool | None, str]:
    """색인이 지금 코퍼스 파일(works·reviews)로 만들어졌는지: 색인 입력 해시 == 코퍼스 출력 해시."""
    if corpus is None or index is None:
        return None, "매니페스트가 없어 대조하지 못함"
    outs = corpus.get("outputs")
    inp = index.get("input")
    files = inp.get("files") if isinstance(inp, dict) else None
    if not isinstance(outs, dict) or not isinstance(files, dict):
        return None, "해시 필드가 없어 대조하지 못함"
    compared = 0
    for name in ("works.jsonl", "reviews.jsonl"):
        want = outs.get(name, {}).get("sha256") if isinstance(outs.get(name), dict) else None
        got = files.get(name)
        if not (isinstance(want, str) and isinstance(got, str)):
            return None, f"해시 필드가 없어 대조하지 못함({name})"
        if want != got:
            return False, f"색인 입력 {name} 해시가 코퍼스 출력과 다르다(색인 재빌드 필요)"
        compared += 1
    return True, f"works·reviews 해시 {compared}개 일치"


def _fmt_int(n: Any) -> str:
    return f"{n:,}" if isinstance(n, int) and not isinstance(n, bool) else ""


def _summary_ko(corpus: dict[str, Any], index: dict[str, Any]) -> str:
    """화면 한 줄 요약. 있는 값만 잇는다(없는 값은 빼고, 지어내지 않는다)."""
    parts: list[str] = []
    venues = corpus.get("by_venue")
    if isinstance(venues, dict) and venues:
        parts.append(" · ".join(sorted(venues)))
    if corpus.get("works") is not None:
        parts.append(f"논문 {_fmt_int(corpus['works'])}편")
    if corpus.get("reviews") is not None:
        parts.append(f"심사평 {_fmt_int(corpus['reviews'])}건")
    ratio = corpus["decisions"].get("reject_ratio")
    if ratio is not None:
        parts.append(f"거절 {ratio * 100:.1f}%")
    if index.get("excerpts") is not None:
        parts.append(f"색인 문장 {_fmt_int(index['excerpts'])}개")
    return " · ".join(parts)


def build_api_meta(data_dir: Path) -> dict[str, Any]:
    """``GET /api`` 응답. 매니페스트 값만 옮긴다."""
    corpus_raw, corpus_reason = read_manifest(data_dir, CORPUS_MANIFEST)
    index_raw, index_reason = read_manifest(data_dir, INDEX_MANIFEST)
    corpus, r1 = _corpus_section(corpus_raw, corpus_reason)
    index, r2 = _index_section(index_raw, index_reason)
    matches, match_note = _index_matches_corpus(corpus_raw, index_raw)
    index["matches_corpus"] = matches
    index["matches_corpus_note"] = match_note
    reasons = r1 + r2
    if matches is False:
        reasons.append(match_note)
    if corpus_raw is None and index_raw is None:
        status = "unavailable"
    elif reasons:
        status = "partial"
    else:
        status = "ok"
    return {
        "service": "neumann",
        "version": neumann.__version__,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reasons": reasons,
        "summary_ko": _summary_ko(corpus, index),
        "corpus": corpus,
        "index": index,
        "endpoints": ["GET /api", "GET /taxonomy", "GET /config/weights"],
    }


# ───────────────────────── 택소노미(03_risk_taxonomy v1.0) ─────────────────────────

TAXONOMY_VERSION = "v1.0"
TAXONOMY_SOURCE = "기획서 부록/설계/03_risk_taxonomy.md v1.0(2026-09-12 확정) §2.3 심각도 표, §2.4 탐지 경로, §3 Tier-1"

# §2.3: 등급 → (이름, 의미, 전형적 귀결)
SEVERITY_SCALE: dict[str, tuple[str, str, str]] = {
    "S5": ("치명적", "결과의 타당성 자체가 무효화됨", "철회/EoC 사유"),
    "S4": ("중대", "주요 재실험 없이는 주장 유지 불가", "request_experiment 다수, reject"),
    "S3": ("상당", "추가 분석·설명 필요, 주장 축소", "request_explanation, major revision"),
    "S2": ("보통", "보완 서술·자료 추가로 해소", "request_clarification, minor revision"),
    "S1": ("경미", "표현·형식 수정", "request_typo, request_edit"),
}

# §2.4: 탐지 경로 코드 → 한국어
DETECT_PATHS: dict[str, str] = {
    "review_text": "심사평",
    "plan_absence": "계획서 부재점검",
    "post_pub_record": "사후기록",
    "paper_metadata": "논문 메타",
}

# §3 Tier-1 카드: 코드 → (정의, 심각도 기본값, 탐지 경로, 위험카드 생성, Macro-F1 측정, 소분류 수)
_TIER1: dict[RiskCode, tuple[str, str, tuple[str, ...], bool, bool, int]] = {
    RiskCode.R0: (
        "가독성·구성·표기·오탈자·그림 라벨 등 서술 층위의 지적. 연구 설계 결함이 아니므로 위험카드를 만들지 않는다.",
        "S1", ("review_text",), False, True, 0,
    ),
    RiskCode.R1: (
        "제시된 실험·데이터·증명이 논문이 내세운 결론을 그 범위 안에서 지지하지 못한다는 지적. "
        "증거를 '더 넓은 조건으로' 확장하라는 요구는 R7(일반화)이고, 같은 조건에서 '증거가 결론에 못 미친다'는 것이 R1이다.",
        "S4", ("review_text", "plan_absence"), True, True, 5,
    ),
    RiskCode.R2: (
        "비교 대상·절단연구·반복 및 불확실성·탐색예산·평가지표 등 '성능 수치를 만들어내는 절차'의 결함. "
        "수치가 오염된 것이 아니라(그건 R3) 수치를 해석할 근거가 부족한 경우.",
        "S4", ("review_text", "plan_absence"), True, True, 7,
    ),
    RiskCode.R3: (
        "훈련과 평가 사이에 정보가 새어 들어가 보고된 성능이 낙관적으로 오염된 상태. "
        "R2는 같은 분할에서 더 돌리거나 지표를 바꾸면 해소되고, R3는 분할·전처리 순서 자체를 다시 짜야 한다.",
        "S5", ("plan_absence", "review_text"), True, True, 8,
    ),
    RiskCode.R4: (
        "데이터의 출처·수집절차·제외기준·결측·레이블 신뢰성·측정조건 이질성·표본크기 등 입력 데이터 자체의 결함. "
        "분할을 아무리 잘해도 남는 문제라는 점에서 R3와 구분된다.",
        "S3", ("plan_absence", "review_text"), True, True, 7,
    ),
    RiskCode.R5: (
        "제3자가 같은 결과를 다시 만들어내는 데 필요한 산출물(코드·데이터·설정·스크립트·자원 정보)의 부재. "
        "판정 기준은 '이 정보를 받으면 다시 구현할 수 있는가'이며, 단지 문장이 읽기 어려운 것은 R0다.",
        "S3", ("review_text", "paper_metadata", "plan_absence"), True, True, 5,
    ),
    RiskCode.R6: (
        "기여의 신규성 부족, 선행연구와의 중복, 관련 문헌 누락, 인용 부정확 등 '이 연구가 문헌 지도 위 어디에 있는가'에 대한 지적. "
        "해소 수단이 주로 문헌 읽기·서술·인용이라는 점에서 R2와 구분된다.",
        "S4", ("review_text",), True, True, 5,
    ),
    RiskCode.R7: (
        "결과가 제시된 실험 조건 밖에서도 성립한다는 근거의 부족, 적용범위 미정의, 외삽 과대주장, 한계 미기술. "
        "같은 조건 안에서 증거 부족이면 R1, 다른 조건으로 확장하는 주장이면 R7.",
        "S4", ("review_text", "plan_absence"), True, True, 6,
    ),
    RiskCode.R8: (
        "계산·모델 예측이 해당 과학 도메인의 실증(합성·계측·임상)과 물리·화학 제약으로 검증되지 않은 상태. "
        "일반 ML 심사 택소노미에는 없고 AI-for-Science 문헌에만 존재하는 실패 모드다.",
        "S4", ("plan_absence", "review_text"), True, True, 7,
    ),
    RiskCode.R9: (
        "철회·우려표명·정정 등 문서화된 사후 기록에 나타난 결함 유형. 심사평 본문에서 추론하지 않으며, "
        "Retraction Watch / Crossref updated-by 등 문서화된 기록이 있을 때만 태깅한다.",
        "S5", ("post_pub_record",), True, False, 9,
    ),
}


def build_taxonomy() -> dict[str, Any]:
    """``GET /taxonomy`` 응답: R0~R9(코드 순)."""
    classes: list[dict[str, Any]] = []
    for code in RiskCode:
        desc, sev, paths, card, f1, n_sub = _TIER1[code]
        slug, name_ko, name_en = RISK_NAMES[code]
        classes.append({
            "code": code.value,
            "slug": slug,
            "name_ko": name_ko,
            "name_en": name_en,
            "description": desc,
            "severity": sev,
            "severity_rank": int(sev[1:]),
            "severity_name_ko": SEVERITY_SCALE[sev][0],
            "detect_from": list(paths),
            "detect_from_ko": [DETECT_PATHS[x] for x in paths],
            "creates_card": card,
            "macro_f1_target": f1,
            "subcodes": [f"{code.value}.{i}" for i in range(1, n_sub + 1)],
        })
    return {
        "version": TAXONOMY_VERSION,
        "source": TAXONOMY_SOURCE,
        "tier1_count": len(classes),
        "tier2_count": sum(len(c["subcodes"]) for c in classes),
        "severity_scale": [
            {"level": lv, "rank": int(lv[1:]), "name_ko": nm, "meaning": mean, "typical": typ}
            for lv, (nm, mean, typ) in SEVERITY_SCALE.items()
        ],
        "detect_paths": dict(DETECT_PATHS),
        "note": "심각도는 기본값이다(03_risk_taxonomy §2.3: UI에서 노출·조정 가능). R0은 비위험 싱크라 위험카드를 만들지 않는다.",
        "classes": classes,
    }


# ───────────────────────── 위험점수 공식(곱, 가중치 없음) ─────────────────────────

SCORE_COMPONENTS: tuple[str, ...] = ("similarity", "frequency", "severity", "confidence")
COMPONENT_LABELS_KO: dict[str, str] = {"similarity": "유사도", "frequency": "빈도", "severity": "심각도", "confidence": "신뢰도"}
FORMULA = "product"
FORMULA_EXPR = "similarity * frequency * severity * confidence"
FORMULA_KO = "위험점수 = 유사도 × 빈도 × 심각도 × 신뢰도 (곱, 가중치 없음)"
FORMULA_DISPLAY = "곱 · 가중치 없음"
DECISION = {
    "source": "docs/decisions.md 2026-09-30 19:15 (PM)",
    "summary": "위험점수는 계획서 §2 정의대로 유사도 × 빈도 × 심각도 × 신뢰도의 곱(가중치 없음). "
    "설계·목업의 가중합(0.3/0.3/0.3/0.1)은 쓰지 않는다.",
}
# 설계 문서·목업에만 있던 가중합 값. 제품은 쓰지 않는다(현재 값으로 보이지 않게 따로 둔다).
LEGACY_DESIGN_WEIGHTS: dict[str, Any] = {
    "status": "제품에서 쓰지 않는 옛 설계값",
    "used_in_product": False,
    "values": {"similarity": 0.30, "frequency": 0.30, "severity": 0.30, "confidence": 0.10},
    "source": "기획서 부록/설계/04_architecture.md §3.8 aggregate_risk 입력 예시 · 목업 가중치 모달",
}


def pipeline_scoring(module_name: str) -> dict[str, Any]:
    """파이프라인 점수 모듈이 실제로 쓰는 공식·가중치. 없으면 state=missing, import 실패면 state=error."""
    info: dict[str, Any] = {"module": module_name, "state": "missing", "formula": None, "weights": None}
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == module_name or module_name.startswith(exc.name + ".")):
            return info
        info["state"] = f"error: 의존 모듈 없음({exc.name})"
        return info
    except Exception as exc:  # noqa: BLE001 - import 실패는 상태로 보고한다(예외 메시지는 쓰지 않는다)
        info["state"] = f"error: {type(exc).__name__}"
        return info
    info["state"] = "ok"
    formula = getattr(mod, "SCORE_FORMULA", None)
    weights = getattr(mod, "SCORE_WEIGHTS", None)
    info["formula"] = formula if isinstance(formula, str) else None
    if isinstance(weights, Mapping) and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in weights.values()
    ):
        info["weights"] = {str(k): float(v) for k, v in weights.items()}
    return info


def pipeline_matches(pipeline: Mapping[str, Any]) -> tuple[bool | None, str]:
    """점수 모듈이 결정(곱, 가중치 없음)과 같은가. 가중치가 있으면 전부 1.0이어야 곱과 같다."""
    if pipeline.get("state") != "ok":
        return None, "파이프라인 점수 모듈이 없거나 불러오지 못해 대조하지 못함."
    formula, weights = pipeline.get("formula"), pipeline.get("weights")
    if formula is None and weights is None:
        return None, "파이프라인 점수 모듈이 공식·가중치를 내놓지 않아 대조하지 못함."
    if formula is not None and "product" not in formula.lower():
        return False, "파이프라인 점수 모듈의 공식이 곱(product)이 아니다. 결정(곱, 가중치 없음)과 다르다."
    if weights is not None:
        if set(weights) != set(SCORE_COMPONENTS):
            return False, "파이프라인 점수 모듈의 가중치 항목이 네 요소(유사도·빈도·심각도·신뢰도)와 다르다."
        if not all(math.isclose(weights[k], 1.0) for k in SCORE_COMPONENTS):
            return False, "파이프라인 점수 모듈이 1.0이 아닌 가중치를 쓴다. 결정(곱, 가중치 없음)과 다르다."
    return True, "파이프라인 점수 모듈이 곱(가중치 없음)으로 계산한다."


def build_weights(pipeline: dict[str, Any] | None = None) -> dict[str, Any]:
    """``GET /config/weights`` 응답. 제품 공식은 곱(가중치 없음), 결정 출처를 함께 적는다."""
    out: dict[str, Any] = {
        "formula": FORMULA,
        "formula_expr": FORMULA_EXPR,
        "formula_ko": FORMULA_KO,
        "weighted": False,
        "weights": None,
        "display": FORMULA_DISPLAY,
        "components": list(SCORE_COMPONENTS),
        "labels_ko": dict(COMPONENT_LABELS_KO),
        "decision": dict(DECISION),
        "legacy_design_weights": copy.deepcopy(LEGACY_DESIGN_WEIGHTS),
    }
    if pipeline is not None:
        pipeline = dict(pipeline)
        pipeline["matches"], pipeline["note"] = pipeline_matches(pipeline)
        out["pipeline"] = pipeline
    return out


# ───────────────────────── 라우트 ─────────────────────────


@router.get("/api", summary="코퍼스·색인 실측 메타(매니페스트 값)")
def api_meta(data_dir: Path = Depends(get_data_dir)) -> dict[str, Any]:
    return build_api_meta(data_dir)


@router.get("/taxonomy", summary="위험 택소노미 R0~R9(03_risk_taxonomy v1.0)")
def taxonomy() -> dict[str, Any]:
    return build_taxonomy()


@router.get("/config/weights", summary="위험점수 공식: 곱(가중치 없음), 결정 출처와 파이프라인 대조")
def config_weights(pipeline: dict[str, Any] = Depends(get_pipeline_scoring)) -> dict[str, Any]:
    return build_weights(pipeline)


__all__ = [
    "CORPUS_MANIFEST",
    "DECISION",
    "FORMULA",
    "INDEX_MANIFEST",
    "LEGACY_DESIGN_WEIGHTS",
    "SCORE_COMPONENTS",
    "TAXONOMY_VERSION",
    "build_api_meta",
    "build_taxonomy",
    "build_weights",
    "get_data_dir",
    "get_pipeline_scoring",
    "pipeline_matches",
    "pipeline_scoring",
    "read_manifest",
    "router",
]
