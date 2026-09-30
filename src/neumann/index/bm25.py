"""Okapi BM25 (표준 라이브러리만). 논문 제목+초록 색인용.

점수 정규화: `score / Σ idf(t)` (질의 낱말 전부, 코퍼스에 없는 낱말은 df=0의 idf로 셈)을 1에서 자른다.
문서가 질의 낱말을 평균 길이에서 한 번씩 다 가지면 약 1.0이다. 질의 최댓값으로 나누지 않는 이유:
무관한 질의에서도 1등 문서가 1.0이 되어 점수 하한이 무의미해진다. 한국어 낱말은 영어 코퍼스에
없으므로(OOV) 분모에만 들어가 어휘 점수를 낮춘다 — 한국어 질의는 임베딩이 맡는다.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

K1 = 1.5
B = 0.75

_TOKEN = re.compile(r"[a-z0-9]+|[가-힣]+|[぀-ヿ一-鿿]+")

STOPWORDS: frozenset[str] = frozenset(
    """
    a an the and or but if then than of to in on at by for with from into onto over under about as is are was were
    be been being this that these those it its we our us you your they their them he she his her i me my
    do does did done can could may might must shall should will would not no nor so such too very via per
    which who whom whose what when where why how all any both each few more most other some own same only
    also just there here up down out off again further once both between through during before after above below
    using use used based paper propose proposed proposes approach method methods new novel show shows shown
    """.split()
)


def _stem(tok: str) -> str:
    """아주 가벼운 어간 처리: 복수형만(과한 어간 추출은 과학 용어를 망친다)."""
    if tok.isascii() and tok.isalpha() and len(tok) > 3:
        if tok.endswith("ies") and len(tok) > 4:
            return tok[:-3] + "y"
        if tok.endswith("sses"):
            return tok[:-2]
        if tok.endswith("s") and not tok.endswith(("ss", "us", "is")):
            return tok[:-1]
    return tok


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN.findall(text.lower()):
        if len(tok) < 2 and not tok.isdigit():
            continue
        if tok in STOPWORDS:
            continue
        out.append(_stem(tok))
    return out


class BM25Index:
    """문서 목록 위의 BM25. `doc_ids` 순서가 점수 배열 순서다."""

    def __init__(
        self,
        doc_ids: Sequence[str],
        doc_len: Sequence[int],
        postings: dict[str, list[tuple[int, int]]],
        *,
        k1: float = K1,
        b: float = B,
    ) -> None:
        self.doc_ids = list(doc_ids)
        self.doc_len = list(doc_len)
        self.postings = postings
        self.k1 = k1
        self.b = b
        self.n_docs = len(self.doc_ids)
        self.avgdl = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0

    @classmethod
    def build(cls, doc_ids: Sequence[str], texts: Iterable[str], *, k1: float = K1, b: float = B) -> BM25Index:
        postings: dict[str, list[tuple[int, int]]] = {}
        lens: list[int] = []
        for i, text in enumerate(texts):
            toks = tokenize(text)
            lens.append(len(toks))
            for term, tf in sorted(Counter(toks).items()):
                postings.setdefault(term, []).append((i, tf))
        if len(lens) != len(doc_ids):
            raise ValueError("doc_ids와 texts의 길이가 다르다")
        return cls(doc_ids, lens, dict(sorted(postings.items())), k1=k1, b=b)

    def idf(self, term: str) -> float:
        df = len(self.postings.get(term, ()))
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def raw_scores(self, query: str) -> list[float]:
        scores = [0.0] * self.n_docs
        if not self.n_docs:
            return scores
        for term in set(tokenize(query)):
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = self.idf(term)
            for doc, tf in plist:
                norm = self.k1 * (1.0 - self.b + self.b * self.doc_len[doc] / (self.avgdl or 1.0))
                scores[doc] += idf * tf * (self.k1 + 1.0) / (tf + norm)
        return scores

    def query_norm(self, query: str) -> float:
        """정규화 분모: 질의 낱말(중복 제거)의 idf 합. OOV 낱말도 df=0으로 센다."""
        return sum(self.idf(t) for t in set(tokenize(query)))

    def scores(self, query: str) -> list[float]:
        """[0, 1]로 정규화한 점수."""
        denom = self.query_norm(query)
        if denom <= 0:
            return [0.0] * self.n_docs
        return [min(1.0, s / denom) for s in self.raw_scores(query)]

    # ── 저장 ──
    def to_json(self) -> dict[str, Any]:
        return {
            "format": "neumann-bm25-v1",
            "k1": self.k1,
            "b": self.b,
            "doc_ids": self.doc_ids,
            "doc_len": self.doc_len,
            "postings": {t: [[d, tf] for d, tf in pl] for t, pl in self.postings.items()},
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> BM25Index:
        if data.get("format") != "neumann-bm25-v1":
            raise ValueError(f"알 수 없는 BM25 형식: {data.get('format')!r}")
        postings = {t: [(int(d), int(tf)) for d, tf in pl] for t, pl in data["postings"].items()}
        return cls(data["doc_ids"], data["doc_len"], postings, k1=data["k1"], b=data["b"])


__all__ = ["B", "K1", "BM25Index", "STOPWORDS", "tokenize"]
