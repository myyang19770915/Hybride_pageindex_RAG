import math
import re
from collections import Counter
from dataclasses import dataclass, field

_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_CJK_PATTERN = re.compile(r"[一-鿿]")


def tokenize(text: str) -> list[str]:
    """Tokenize mixed zh/en text.

    ASCII runs become word tokens; CJK is split into single characters so that
    Chinese phrases match at the character level (the previous whole-run
    tokenizer treated "真空度不足" as one opaque token).
    """
    lowered = text.lower()
    return _WORD_PATTERN.findall(lowered) + _CJK_PATTERN.findall(lowered)


@dataclass
class BM25Index:
    """Minimal in-process BM25 ranker over a small document/page corpus."""

    k1: float = 1.5
    b: float = 0.75
    _ids: list[str] = field(default_factory=list)
    _doc_tokens: dict[str, Counter] = field(default_factory=dict)
    _doc_len: dict[str, int] = field(default_factory=dict)
    _df: Counter = field(default_factory=Counter)
    _avgdl: float = 0.0

    def fit(self, corpus: dict[str, str]) -> "BM25Index":
        self._ids = list(corpus)
        total_len = 0
        for doc_id, text in corpus.items():
            tokens = tokenize(text)
            counts = Counter(tokens)
            self._doc_tokens[doc_id] = counts
            self._doc_len[doc_id] = len(tokens)
            total_len += len(tokens)
            for term in counts:
                self._df[term] += 1
        self._avgdl = (total_len / len(corpus)) if corpus else 0.0
        return self

    def _idf(self, term: str) -> float:
        n = len(self._ids)
        df = self._df.get(term, 0)
        # BM25 idf with +1 smoothing to stay non-negative.
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score(self, query: str, doc_id: str) -> float:
        counts = self._doc_tokens.get(doc_id)
        if not counts:
            return 0.0
        doc_len = self._doc_len[doc_id]
        score = 0.0
        for term in tokenize(query):
            freq = counts.get(term, 0)
            if freq == 0:
                continue
            denom = freq + self.k1 * (1 - self.b + self.b * doc_len / (self._avgdl or 1.0))
            score += self._idf(term) * (freq * (self.k1 + 1)) / denom
        return score

    def rank(self, query: str) -> list[str]:
        scored = sorted(self._ids, key=lambda doc_id: self.score(query, doc_id), reverse=True)
        return [doc_id for doc_id in scored if self.score(query, doc_id) > 0]


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Fuse several ranked id lists into one via Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda doc_id: scores[doc_id], reverse=True)
