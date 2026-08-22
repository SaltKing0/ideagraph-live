"""Embeddings: lokal via sentence-transformers (Default: all-MiniLM-L6-v2).

Für Tests gibt es einen HashEmbedder — deterministisch, ohne Modell-Download.
"""

from __future__ import annotations

import hashlib


class Embedder:
    """Lädt sentence-transformers lazy — erst beim ersten echten Embedding."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._ensure_model()
        return model.encode(text).tolist()


class HashEmbedder:
    """Deterministischer Test-Embedder: bag-of-words-Projektion auf feste Dim.

    Kein Modell, kein Netzwerk — gleicher Text → gleicher Vektor,
    ähnlicher Text (Wortüberlappung) → ähnlicher Vektor.
    """

    DIM = 64

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.DIM
        for word in text.lower().split():
            h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
            idx = h % self.DIM
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


def get_embedder(name: str = "st") -> Embedder | HashEmbedder:
    if name == "hash":
        return HashEmbedder()
    return Embedder()
