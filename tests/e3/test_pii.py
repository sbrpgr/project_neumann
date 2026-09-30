"""E3-L1c: 개인정보 마스킹 강화(전화번호·주민번호) 테스트."""

from __future__ import annotations

import random
import re
import time

import pytest

from neumann.analyze.pii import (
    ascii_digits,
    find_pii,
    has_pii,
    mask_pii,
    mask_pii_counts,
    mask_plan_text,
    plan_document_from_text,
)
from neumann.models import PlanDocument, redact_pii, sha256_text
from tests.fixtures.loader import DEMO_PLANS, NEGATIVE_PLAN, plan_text

# 전화번호 변형: 국내·국제, 구분자 변형(하이픈류·공백·점·괄호·가운뎃점·섞임), 유니코드 숫자
PHONE_VARIANTS = [
    "010-1234-5678",
    "010 1234 5678",
    "010.1234.5678",
    "01012345678",
    "010 - 1234 - 5678",
    "010·1234·5678",
    "010‐1234‐5678",  # U+2010 하이픈
    "010–1234–5678",  # en dash
    "010−1234−5678",  # 수학 빼기 기호
    "02-123-4567",
    "02-1234-5678",
    "(02) 123-4567",
    "031-123-4567",
    "0505-123-4567",
    "+82-10-1234-5678",
    "+82 10 1234 5678",
    "+82 (0)10 1234 5678",
    "+82-2-123-4567",
    "82-10-1234-5678",
    "+1 (555) 123-4567",
    "+44 20 7946 0958",
    "０１０－１２３４－５６７８",  # 전각 숫자·전각 하이픈
    "٠١٠-١٢٣٤-٥٦٧٨",  # 아랍-인도 숫자
    "०१० १२३४ ५६७८",  # 데바나가리 숫자
    "＋82 10 1234 5678",  # 전각 더하기
]

# 단서(전화·Tel·연락처)가 있을 때만 가리는 짧은 번호
CUED_PHONES = [
    ("Tel: 1588-1234", "Tel: [PHONE]"),
    ("전화 123-4567", "전화 [PHONE]"),
    ("대표번호(문의) 1661-0000", "대표번호(문의) [PHONE]"),
]

# 오탐 방지: 그대로 남아야 하는 것
PRESERVED = [
    "2024",
    "0.95",
    "10.1234/abc",
    "R2.3",
    "2023-2024",
    "1600-1700",
    "2024-01-15",
    "2021.03.15",
    "문의 2024-01-15",
    "p < 0.001",
    "12,000건",
    "1,234,567,890",
    "80/10/10",
    "0.1234 0.5678 0.9012",
    "0.012 0.034 0.056",
    "0.123456789",
    "R2 = 0.95, MAE 0.012",
    "ResNet-50",
    "vIoU@0.3",
    "https://doi.org/10.1234/abc.0123456789",
    "doi:10.1016/j.cell.2020.01234",
    "arXiv:2401.01234",
    "ex_0123456789abcdef",
    "192.168.0.1",
    "ISBN 978-89-1234-567-8",
    "0-306-40615-2",
    "v1.0.2345678901",
    "offset 1024-2048",
    "start=1234, end=5678",
    "[1234:5678]",
    "L12-L34",
    "Table 3.2.1",
    "1e-5",
    "seed 42, 5 folds",
    "abc01012345678xyz",
    "010\n1234-5678",
]


@pytest.mark.parametrize("raw", PHONE_VARIANTS)
def test_phone_variant_masked(raw: str) -> None:
    out = mask_pii(raw)
    assert out == "[PHONE]", (raw, out)


def test_at_least_ten_phone_variants() -> None:
    assert len(PHONE_VARIANTS) >= 10
    masked = [v for v in PHONE_VARIANTS if mask_pii(v) == "[PHONE]"]
    assert len(masked) == len(PHONE_VARIANTS)


@pytest.mark.parametrize("raw", PHONE_VARIANTS)
def test_phone_variant_in_korean_sentence(raw: str) -> None:
    text = f"문의는 연구책임자 연락처 {raw}로 해 주세요."
    out = mask_pii(text)
    assert out == "문의는 연구책임자 연락처 [PHONE]로 해 주세요.", out
    assert not re.search(r"\d", ascii_digits(out))


@pytest.mark.parametrize(("raw", "expected"), CUED_PHONES)
def test_cued_short_numbers(raw: str, expected: str) -> None:
    assert mask_pii(raw) == expected


def test_short_numbers_without_cue_are_kept() -> None:
    for raw in ("1588-1234", "123-4567", "1661-0000"):
        assert mask_pii(raw) == raw


@pytest.mark.parametrize("raw", PRESERVED)
def test_false_positive_preserved(raw: str) -> None:
    assert mask_pii(raw) == raw
    assert not has_pii(raw)


def test_mixed_text_masks_only_pii() -> None:
    text = (
        "2024년 결과: R2 0.95, MAE 0.012 (R2.3 위험). DOI 10.1234/abc 참고.\n"
        "책임자 연락처 010-1234-5678, 사무실 (02) 123-4567, 메일 pi@lab.ac.kr, ORCID 0000-0002-1825-0097.\n"
        "12,000건을 80/10/10으로 나눈다."
    )
    out, counts = mask_pii_counts(text)
    assert counts == {"phone": 2, "email": 1, "orcid": 1}
    assert out == (
        "2024년 결과: R2 0.95, MAE 0.012 (R2.3 위험). DOI 10.1234/abc 참고.\n"
        "책임자 연락처 [PHONE], 사무실 [PHONE], 메일 [EMAIL], ORCID [ORCID].\n"
        "12,000건을 80/10/10으로 나눈다."
    )


def test_several_numbers_in_one_chain() -> None:
    assert mask_pii("010-1234-5678 010-9876-5432") == "[PHONE] [PHONE]"
    assert mask_pii("010-1234-5678 2024") == "[PHONE] 2024"


def test_rrn_forms() -> None:
    assert mask_pii("주민번호 900101-1234567") == "주민번호 [RRN]"
    assert mask_pii("900101 - 2234567 입니다") == "[RRN] 입니다"
    assert mask_pii("9001011234567") == "[RRN]"
    assert mask_pii("900101-1******") == "[RRN]"  # 뒷자리를 가린 형태도 생년월일·성별이 드러난다
    assert mask_pii("９００１０１-１２３４５６７") == "[RRN]"
    # 월·일이 유효하지 않으면 주민번호로 보지 않는다
    assert mask_pii("901301-1234567") == "901301-1234567"
    assert mask_pii("900132-1234567") == "900132-1234567"


def test_email_orcid_reuse_models_regex() -> None:
    text = "연락: kim.lab@univ.ac.kr / ORCID 0000-0002-1825-0097 / 지표 vIoU@0.3"
    assert mask_pii(text) == redact_pii(text)


def test_idempotent() -> None:
    text = "010-1234-5678, a@b.com, 900101-1234567, 0000-0002-1825-0097"
    once = mask_pii(text)
    assert mask_pii(once) == once
    assert not has_pii(once)


def test_spans_are_original_offsets_for_unicode_digits() -> None:
    text = "전화 ０１０-１２３４-５６７８ 끝"
    spans = find_pii(text)
    assert len(spans) == 1
    s = spans[0]
    assert s.kind == "phone"
    assert text[s.start : s.end] == "０１０-１２３４-５６７８"


def test_url_and_doi_are_not_phone() -> None:
    text = "https://example.org/files/010-1234-5678.pdf 와 10.5555/010-1234-5678"
    assert mask_pii(text) == text


@pytest.mark.parametrize("name", [*DEMO_PLANS, NEGATIVE_PLAN])
def test_fixture_plans_have_no_false_positive(name: str) -> None:
    text = plan_text(name)
    assert mask_pii(text) == text


# ── 성능: 공개 서버 입력이라 긴 숫자 줄로 멈추지 않아야 한다(서비스 거부 방지) ──────────


def _timed(text: str) -> tuple[float, str, dict[str, int]]:
    t0 = time.perf_counter()
    out, counts = mask_pii_counts(text)
    return time.perf_counter() - t0, out, counts


def test_long_line_of_space_joined_numbers_is_fast() -> None:
    rng = random.Random(0)
    text = " ".join(str(rng.randint(1, 99999)) for _ in range(3000))
    elapsed, out, _ = _timed(text)
    assert elapsed < 1.0, f"숫자 3,000개 한 줄에 {elapsed:.2f}s"
    assert len(out) > 0


@pytest.mark.parametrize(
    "text",
    [
        "0.1 " * 3000,  # 소수 3,000개
        "-".join(["12"] * 5000),  # 하이픈으로 이은 숫자 5,000개
        "(0) " * 5000,
        "a." * 20000 + "@b.com",  # 이메일 정규식이 제곱 시간이 되는 긴 토큰
        "a" * 50000,
        ("a." * 30 + "@") * 2000,
    ],
    ids=["decimals", "hyphens", "parens", "long-local-part", "long-token", "many-at"],
)
def test_adversarial_inputs_are_fast(text: str) -> None:
    elapsed, _, _ = _timed(text)
    assert elapsed < 1.0, f"{elapsed:.2f}s"


def test_many_phones_masked_quickly() -> None:
    elapsed, out, counts = _timed("010-1234-5678 " * 2000)
    assert elapsed < 1.0 and counts == {"phone": 2000}
    assert out == "[PHONE] " * 2000


def test_phone_found_inside_long_number_chain() -> None:
    """묶음 창 상한을 둬도 긴 사슬 가운데의 번호는 잡힌다."""
    prefix = " ".join(str(n) for n in range(1, 40))
    text = f"{prefix} 010-1234-5678 7 8 9"
    assert mask_pii(text) == f"{prefix} [PHONE] 7 8 9"


def test_plan_document_from_adversarial_text_is_fast() -> None:
    t0 = time.perf_counter()
    plan, _ = plan_document_from_text("a." * 20000 + "\n" + " ".join(["12"] * 3000), "sess-dos")
    assert time.perf_counter() - t0 < 1.0
    assert len(plan.lines) == 2


def test_long_local_part_email_still_masked() -> None:
    assert mask_pii("x " + "a." * 20000 + "b@c.com").endswith("[EMAIL]")
    assert mask_pii("a@b.com@c.com") == "[EMAIL]@c.com"  # EMAIL_RE.finditer와 같은 결과


def test_plan_document_from_text_masks_phone_and_rrn() -> None:
    raw = plan_text("plan.md") + "\n책임자 연락처: 010-1234-5678 / 주민번호 900101-1234567 / pi@lab.ac.kr\r\n"
    plan, counts = plan_document_from_text(raw, "sess-1")
    assert counts == {"phone": 1, "rrn": 1, "email": 1}
    body = plan.text
    assert "[PHONE]" in body and "[RRN]" in body and "[EMAIL]" in body
    assert "1234-5678" not in body and "1234567" not in body
    assert plan.plan_id == sha256_text(body)
    assert "\r" not in body


def test_plan_document_unchanged_for_clean_plan() -> None:
    raw = plan_text("plan_medimaging.md")
    plan, counts = plan_document_from_text(raw, "sess-2")
    assert counts == {}
    assert plan.plan_id == PlanDocument.from_text(raw, "sess-2").plan_id
    body, _ = mask_plan_text(raw)
    assert body == plan.text
