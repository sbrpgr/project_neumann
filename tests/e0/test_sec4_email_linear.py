"""SEC-4: 이메일 검사가 긴 토큰에서 제곱 시간이 되지 않고, 결과는 EMAIL_RE.finditer와 같다."""

from __future__ import annotations

import random
import time

import pytest

from neumann.models import EMAIL_RE, contains_pii, email_spans, redact_pii


def _ref_spans(text: str) -> list[tuple[int, int]]:
    return [m.span() for m in EMAIL_RE.finditer(text)]


CASES = [
    "",
    "no email here",
    "contact a.b+c@example.com now",
    "x@y@example.com",
    "a@b.com, c@d.org; e@f.co.kr",
    "vIoU@0.3 is a metric",
    "a@b.comx@c.org",
    "trailing a@b.c",
    "@@@@",
    "a@-.xy",
    "first.last@sub-domain.example.io.",
    "a@b.c.d.e.f.gh",
    "@example.com",
    "name@@example.com",
]


@pytest.mark.parametrize("text", CASES)
def test_matches_reference_on_cases(text):
    assert email_spans(text) == _ref_spans(text)
    assert redact_pii(text) == EMAIL_RE.sub("[EMAIL]", text)  # ORCID 없는 입력이라 이메일 가림만 비교된다


def test_matches_reference_on_random_strings():
    rng = random.Random(20260930)
    alphabet = "ab.-_+%@ \n0Z"
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        assert email_spans(text) == _ref_spans(text), repr(text)
        assert redact_pii(text) == EMAIL_RE.sub("[EMAIL]", text), repr(text)


@pytest.mark.parametrize(
    "text",
    [
        "a" * 200_000,  # @ 없는 긴 토큰(보고된 ReDoS)
        "a" * 200_000 + "@",  # 끝에만 @
        "a@" * 100_000,  # @가 많은 토큰
        "a" * 100_000 + "@" + "b" * 100_000,  # 도메인 쪽이 긴 토큰
        "a@" + "b." * 100_000,  # 점이 많은 도메인
    ],
    ids=["no_at", "at_end", "many_at", "long_domain", "many_dots"],
)
def test_long_tokens_are_fast(text):
    t0 = time.perf_counter()
    contains_pii(text)
    redact_pii(text)
    assert time.perf_counter() - t0 < 1.0


@pytest.mark.parametrize("n", [1, 63, 64, 65, 252, 253, 254, 255, 256, 257, 300, 5000])
def test_long_domains_match_reference(n):
    """도메인 길이 상한이 없다: 아주 긴 도메인도 옛 구현(EMAIL_RE.finditer·sub)과 같게 가린다."""
    for text in (f"x.y@{'d' * n}.org", f"a@{'b.' * n}com tail", f"pre {'l' * n}@ex.io post"):
        assert email_spans(text) == _ref_spans(text)
        assert redact_pii(text) == EMAIL_RE.sub("[EMAIL]", text)
        assert contains_pii(text) is bool(_ref_spans(text))
