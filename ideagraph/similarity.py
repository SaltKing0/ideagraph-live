"""Similarity: Kosinus-Ähnlichkeit + k nächste Nachbarn."""

from __future__ import annotations

import math


def cosine(a: list[float], b: list[float]) -> float:
    """Kosinus-Ähnlichkeit. Audit #8: ungleiche Dimensionen sind ein Datenfehler
    (z. B. 384-dim ST-Vektor vs. 64-dim Hash-Vektor in einem Brain) — ein stiller
    Truncation auf die kürzere Länge erzeugt plausibel aussehende Scores und kann
    an der Dedupe-Schwelle einen falschen Auto-Merge auslösen. Deshalb: hart failen."""
    if len(a) != len(b):
        raise ValueError(
            f"cosine: dimension mismatch ({len(a)} vs {len(b)}) — "
            "inhomogene Embedder im selben Brain? Vektoren sind nicht vergleichbar.")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def knn(query: list[float], candidates: dict[str, list[float]], k: int = 3) -> list[tuple[str, float]]:
    """Liefert die k nächsten Nachbarn als (id, similarity), absteigend sortiert.

    Audit #8-Follow-up (Fix-Welle 2): fremd-dimensionale Kandidaten werden
    übersprungen statt den ganzen Query zu crashen — dieselbe Zwei-Ebenen-
    Entscheidung wie bei _find_duplicate: das Primitiv cosine() streng,
    die Call-Sites tolerant. Ein Brain mit ein paar Alt-Vektoren falscher
    Dimension (z. B. nach Embedder-Wechsel) degradiert damit sauber auf die
    kompatiblen Nachbarn."""
    query_dim = len(query)
    scored = [(nid, cosine(query, vec)) for nid, vec in candidates.items()
              if len(vec) == query_dim]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:k]
