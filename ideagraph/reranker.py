"""Cross-Encoder-Reranking (Roadmap V2#1) — optionaler zweiter Retrieval-Pass.

Hybrid (dense+BM25, RRF) liefert die Top-K Kandidaten. Ein Cross-Encoder
bewertet jedes (query, Kandidat)-Paar GEMEINSAM — statt Kosinus auf getrennten
Embeddings — und re-sortiert die Top-K auf die Top-N. Laut Roadmap ist das der
einzeln größte gemessene Add-on (minus ein Drittel Residual-Failures).

Kein neuer Pflicht-Dependency: Default ist `None`/Identity, das Verhalten ist
also unverändert. Ein echtes Modell wird nur geladen, wenn angefragt
(`IDEAGRAPH_RERANKER=st` für sentence-transformers CrossEncoder, oder ein
Modellname/-Pfad als Wert). `ReverseReranker` ist ein deterministischer Test-
Stub, der beweist, dass der Rerank-Pass die finale Rangfolge bestimmt.
"""

from __future__ import annotations

import os


class Reranker:
    """Protocol: re-sortiert (query, Kandidaten) auf die Top-k."""

    def rerank(self, query: str, candidates, k: int):
        # candidates: list[(node_id, text, rrf_score)]
        # returns:    list[(node_id, text, rrf_score)] — top-k in Rerank-Reihenfolge
        raise NotImplementedError


class ReverseReranker(Reranker):
    """Deterministischer Test-Stub: kehrt die Kandidaten-Reihenfolge um.

    Zweck: beweisen, dass der Rerank-Pass die finale Rangfolge bestimmt
    (Pipeline-Integration) — nicht, dass das Modell qualitativ besser ist.
    """

    def rerank(self, query: str, candidates, k: int):
        return list(reversed(candidates))[:k]


class CrossEncoderReranker(Reranker):
    """Echtes Cross-Encoder-Modell (sentence-transformers), optional geladen."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "IDEAGRAPH_RERANKER=st benötigt 'sentence-transformers' "
                "(pip install sentence-transformers)."
            ) from exc
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, candidates, k: int):
        pairs = [(query, text) for _, text, _ in candidates]
        scores = self.model.predict(pairs, show_progress_bar=False)
        scored = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
        return [cand for cand, _ in scored][:k]


def get_reranker():
    """Factory aus IDEAGRAPH_RERANKER: 'none' (Default) | 'st' | Modellname/Pfad."""
    mode = os.environ.get("IDEAGRAPH_RERANKER", "none").strip().lower()
    if not mode or mode == "none":
        return None
    if mode == "st":
        return CrossEncoderReranker()
    return CrossEncoderReranker(model_name=mode)
