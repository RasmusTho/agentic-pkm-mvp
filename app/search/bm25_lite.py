from __future__ import annotations
from collections import Counter
from math import log
from typing import Iterable, Tuple, List
import re

_W = re.compile(r"\w+")

def _tok(s: str) -> list[str]:
    return [m.group(0).lower() for m in _W.finditer(s or "")]

class BM25Lite:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: dict[str, list[str]] = {}
        self.df: Counter[str] = Counter()
        self.doc_len: dict[str, int] = {}
        self.N = 0
        self.avgdl = 0.0

    def add(self, doc_id: str, text: str) -> None:
        if doc_id in self.docs:
            return
        tokens = _tok(text)
        self.docs[doc_id] = tokens
        self.doc_len[doc_id] = len(tokens)
        self.N += 1
        self.avgdl = (sum(self.doc_len.values()) / self.N) if self.N else 0.0
        for t in set(tokens):
            self.df[t] += 1

    def add_many(self, pairs: Iterable[Tuple[str, str]]) -> None:
        for did, text in pairs:
            self.add(did, text)

    def _idf(self, term: str) -> float:
        n = self.df.get(term, 0)
        if n == 0: return 0.0
        return log(1 + (self.N - n + 0.5) / (n + 0.5))

    def score(self, query: str, doc_id: str) -> float:
        q = _tok(query)
        d = self.docs.get(doc_id, [])
        if not d or not q: return 0.0
        tf = Counter(d)
        dl = self.doc_len.get(doc_id, 0)
        norm = 1 - self.b + self.b * (dl / (self.avgdl or 1.0))
        s = 0.0
        for t in q:
            f = tf.get(t, 0)
            if f == 0: continue
            s += self._idf(t) * (f * (self.k1 + 1)) / (f + self.k1 * norm)
        return s

    def query(self, query: str, k: int = 10) -> List[tuple[str, float]]:
        scores = [(did, self.score(query, did)) for did in self.docs.keys()]
        scores.sort(key=lambda x: x[1], reverse=True)
        return [x for x in scores[:k] if x[1] > 0.0]

_BM25: BM25Lite | None = None

def get_bm25() -> BM25Lite:
    global _BM25
    if _BM25 is None:
        _BM25 = BM25Lite()
    return _BM25