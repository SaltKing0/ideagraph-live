"""Hybrid-Retrieval: dense (Kosinus) + BM25, fusioniert via Reciprocal Rank Fusion.

Roadmap V2#1: "zuerst Hybrid dense+BM25 mit getuntem Fusion (hoechster ROI)".
BM25 ist reine Textstatistik — keine Dependency, kein Modell. Die Fusion über
RRF kombiniert beide Rankings robust (unabhängig von ihrer Skala), bevor
später ein Cross-Encoder-Reranking der Top-K dazukommt.
"""

from __future__ import annotations

import math

import numpy as np

from .brain_engine import BrainEngine
from .similarity import cosine


def tokenize(text: str) -> list[str]:
    return text.lower().split()


class BM25:
    """BM25-Scorer. Der Index (df, doc_len, per-doc tf) wird EINMAL im
    Konstruktor gebaut — `scores()` schaut nur noch nach (Audit #10: die alte
    Version re-tokenisierte das gesamte Corpus bei jedem Query zweimal,
    0,225 s/Query @2k Docs)."""

    def __init__(self, corpus: list[str], k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.N = len(corpus)
        self.doc_len: list[int] = []
        self.avgdl = sum(self.doc_len) / self.N if self.N else 0.0
        self.df: dict[str, int] = {}
        self._tf: list[dict[str, int]] = []
        for doc in corpus:
            tf: dict[str, int] = {}
            for t in tokenize(doc):
                tf[t] = tf.get(t, 0) + 1
            self._tf.append(tf)
            self.doc_len.append(sum(tf.values()))
            for term in tf:
                self.df[term] = self.df.get(term, 0) + 1
        self.avgdl = sum(self.doc_len) / self.N if self.N else 0.0

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))

    def scores(self, query_tokens: list[str]) -> list[float]:
        """BM25-Score je Dokument (gleiche Reihenfolge wie corpus)."""
        if self.N == 0:
            return []
        out: list[float] = []
        for tf, dl in zip(self._tf, self.doc_len):
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


def retrieve_candidates(engine: BrainEngine, query: str, rerank_k: int = 30) -> tuple[list[str], dict[str, str], list[tuple[str, float]]]:
    """Gemeinsame Kandidatenbeschaffung für retrieve()/Rerank-Pfad."""
    nodes = engine.brain.read_nodes()
    # Audit #7: Tombstones sind "vergessen" — sie dürfen nicht als Suchantworten
    # zurückkommen (consolidate/_find_duplicate excluden sie bereits).
    nodes = [n for n in nodes if n.status != "tombstone"]
    if not nodes:
        return [], {}, []
    node_ids = [n.id for n in nodes]
    qvec = engine.embedder.embed(query)

    vecs = engine.brain.vectors_for(set(node_ids), lambda t: engine.embedder.embed(t))
    # Audit #8 (Folgefix): Vektoren mit fremder Dimension sind nicht vergleichbar
    # mit der Query (anderer Embedder im selben Brain, z. B. Demo-Seed mit
    # vorberechneten ST-Vektoren + HashEmbedder-Engine). Statt still zu truncieren
    # (alter cosine-Bug) werden sie übersprungen — die Dense-Stufe degradiert,
    # BM25 bleibt voll wirksam.
    # Audit #60: die Dense-Stufe läuft als numpy-Matmul über L2-normalisierte
    # Vektoren statt als pure-Python-cosine-Loop (0,150 s/Query @2k×384-dim →
    # sub-2 ms). Fremd-dimensionale/leere Vektoren bleiben ausgeschlossen.
    dense_ids = [nid for nid in node_ids
                 if nid in vecs and vecs[nid] and len(vecs[nid]) == len(qvec)]
    if dense_ids:
        M = np.array([vecs[nid] for nid in dense_ids], dtype=np.float64)
        M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-12)
        q = np.asarray(qvec, dtype=np.float64)
        q = q / (np.linalg.norm(q) + 1e-12)
        sims = M @ q
        dense = [(nid, float(s)) for nid, s in zip(dense_ids, sims)]
    else:
        dense = []

    bm = BM25([n.text for n in nodes])
    bm_scores = bm.scores(tokenize(query))
    bm_rank = [(nid, s) for nid, s in zip(node_ids, bm_scores) if s > 0.0]

    # Audit #37: eine Nonsense-Query lieferte sonst 5 "Ergebnisse" mit
    # RRF-Scores ≈ 0.033 — beide Ränge bedeutungslos, aber als Ranking
    # präsentiert. Knoten ohne jede Überlappung (dense 0.0 UND BM25 0.0)
    # fliegen vor der Fusion raus.
    dense_ids = {nid for nid, s in dense if s > 0.0}
    bm_ids = {nid for nid, s in bm_rank}
    overlap = dense_ids | bm_ids
    dense = [(nid, s) for nid, s in dense if nid in overlap]
    bm_rank = [(nid, s) for nid, s in bm_rank if nid in overlap]
    if not dense and not bm_rank:
        return node_ids, {n.id: n.text for n in nodes}, []

    candidates = rrf_fuse([dense, bm_rank], k=60)[:rerank_k]
    return node_ids, {n.id: n.text for n in nodes}, candidates


def retrieve(engine: BrainEngine, query: str, k: int = 5, rerank_k: int = 30) -> list[tuple[str, float]]:
    """Hybrid-Retrieval über den Brain. Liefert top-k (node_id, rrf_score).

    Dense: Kosinus der Query-Embedding gegen die gecachten Node-Vektoren.
    BM25: lexikalische Überlappung gegen die Node-Texte.
    Fusion: RRF über die beiden Rangfolgen.
    Rerank (V2#1, optional): Hybrid liefert top-`rerank_k` Kandidaten; ein auf
    dem Engine gesetzter `reranker` (Cross-Encoder o. Stub) sortiert sie neu auf
    top-`k`. Ohne Reranker (Default) bleibt das Verhalten identisch.
    """
    node_ids, text_by_id, candidates = retrieve_candidates(engine, query, rerank_k)
    if not candidates:
        return []

    reranker = getattr(engine, "reranker", None)
    if reranker is None:
        return candidates[:k]

    with_text = [(nid, text_by_id[nid], score) for nid, score in candidates]
    reranked = reranker.rerank(query, with_text, k)
    return [(nid, score) for nid, _, score in reranked]
