"""Hybrid-Retrieval: dense (Kosinus) + BM25, fusioniert via Reciprocal Rank Fusion.

Roadmap V2#1: "zuerst Hybrid dense+BM25 mit getuntem Fusion (hoechster ROI)".
BM25 ist reine Textstatistik — keine Dependency, kein Modell. Die Fusion über
RRF kombiniert beide Rankings robust (unabhängig von ihrer Skala), bevor
später ein Cross-Encoder-Reranking der Top-K dazukommt.
"""

from __future__ import annotations

import math

from .brain_engine import BrainEngine
from .similarity import cosine


def tokenize(text: str) -> list[str]:
    return text.lower().split()


class BM25:
    """Best-25-Scorer (pure Python). k1/b Defaults nach Standard-Literatur."""

    def __init__(self, corpus: list[str], k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.N = len(corpus)
        self.doc_len = [len(tokenize(d)) for d in corpus]
        self.avgdl = sum(self.doc_len) / self.N if self.N else 0.0
        self.df: dict[str, int] = {}
        for doc in corpus:
            for term in set(tokenize(doc)):
                self.df[term] = self.df.get(term, 0) + 1

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))

    def scores(self, query_tokens: list[str]) -> list[float]:
        """BM25-Score je Dokument (gleiche Reihenfolge wie corpus)."""
        if self.N == 0:
            return []
        out: list[float] = []
        for i, doc in enumerate(self.corpus):
            dl = self.doc_len[i]
            tf: dict[str, int] = {}
            for t in tokenize(doc):
                tf[t] = tf.get(t, 0) + 1
            s = 0.0
            for t in query_tokens:
                f = tf.get(t, 0)
                if f == 0:
                    continue
                denom = f + self.k1 * (1.0 - self.b + self.b * dl / self.avgdl)
                s += self.idf(t) * (f * (self.k1 + 1.0)) / denom
            out.append(s)
        return out


def rrf_fuse(ranked_lists: list[list[tuple[str, float]]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: vereint mehrere (id, score)-Rankings zu einem.

    Jedes Ranking wird nach Score absteigend sortiert; jeder Rang trägt
    1/(k + rank) bei. k=60 ist der übliche RRF-Standard.
    """
    fused: dict[str, float] = {}
    for rl in ranked_lists:
        ordered = sorted(rl, key=lambda x: x[1], reverse=True)
        for rank, (nid, _) in enumerate(ordered):
            fused[nid] = fused.get(nid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def retrieve(engine: BrainEngine, query: str, k: int = 5, rerank_k: int = 30) -> list[tuple[str, float]]:
    """Hybrid-Retrieval über den Brain. Liefert top-k (node_id, rrf_score).

    Dense: Kosinus der Query-Embedding gegen die gecachten Node-Vektoren.
    BM25: lexikalische Überlappung gegen die Node-Texte.
    Fusion: RRF über die beiden Rangfolgen.
    Rerank (V2#1, optional): Hybrid liefert top-`rerank_k` Kandidaten; ein auf
    dem Engine gesetzter `reranker` (Cross-Encoder o. Stub) sortiert sie neu auf
    top-`k`. Ohne Reranker (Default) bleibt das Verhalten identisch.
    """
    nodes = engine.brain.read_nodes()
    if not nodes:
        return []
    node_ids = [n.id for n in nodes]
    qvec = engine.embedder.embed(query)

    vecs = engine.brain.vectors_for(set(node_ids), lambda t: engine.embedder.embed(t))
    dense = [(nid, cosine(qvec, vecs.get(nid, []))) for nid in node_ids]

    bm = BM25([n.text for n in nodes])
    bm_scores = bm.scores(tokenize(query))
    bm_rank = [(nid, s) for nid, s in zip(node_ids, bm_scores)]

    candidates = rrf_fuse([dense, bm_rank], k=60)[:rerank_k]

    reranker = getattr(engine, "reranker", None)
    if reranker is None:
        return candidates[:k]

    text_by_id = {n.id: n.text for n in nodes}
    with_text = [(nid, text_by_id[nid], score) for nid, score in candidates]
    reranked = reranker.rerank(query, with_text, k)
    return [(nid, score) for nid, _, score in reranked]
