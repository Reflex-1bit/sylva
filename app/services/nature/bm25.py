"""Sylva - Nature arm: Okapi BM25 over pre-tokenised documents (numpy only)."""

from collections import Counter

import numpy as np


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.doc_len = np.array([len(d) for d in docs], dtype=np.float64)
        self.avgdl = float(self.doc_len.mean()) if self.n and self.doc_len.sum() else 1.0
        self.tf: dict[str, list[tuple[int, int]]] = {}
        for i, d in enumerate(docs):
            for term, c in Counter(d).items():
                self.tf.setdefault(term, []).append((i, c))
        self.idf = {
            t: float(np.log(1.0 + (self.n - len(p) + 0.5) / (len(p) + 0.5)))
            for t, p in self.tf.items()
        }

    def scores(self, query_tokens: list[str]) -> np.ndarray:
        out = np.zeros(self.n, dtype=np.float64)
        for term in set(query_tokens):
            postings = self.tf.get(term)
            if not postings:
                continue
            idx = np.array([p[0] for p in postings])
            tf = np.array([p[1] for p in postings], dtype=np.float64)
            norm = self.k1 * (1.0 - self.b + self.b * self.doc_len[idx] / self.avgdl)
            out[idx] += self.idf[term] * tf * (self.k1 + 1.0) / (tf + norm)
        return out
