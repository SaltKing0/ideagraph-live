"""Edge-Vorschläge: aus den k nächsten Nachbarn werden getypte Vorschläge.

Regeln (bewusst simpel, lernorientiert):
- sim >= 0.75          → "ähnlich"
- 0.45 <= sim < 0.75   → "erweitert" (Nachbar ist thematisch verwandt)
- darunter             → kein Vorschlag

Die "kontradiktorisch"-Erkennung ist in v0.0.1 bewusst noch nicht automatisiert —
die kommt, wenn der Loop stabil läuft.
"""

from __future__ import annotations

from .model import Edge
from .similarity import cosine

THRESHOLD_SIMILAR = 0.75
THRESHOLD_EXTEND = 0.45


def suggest_edges(source_id: str, query_vec: list[float],
                  candidates: dict[str, list[float]], k: int = 3) -> list[Edge]:
    """Schlägt Edges der neuen Idee (source_id) zu den k nächsten Nachbarn vor."""
    from .similarity import knn
    edges: list[Edge] = []
    seen: set[str] = set()
    for nid, sim in knn(query_vec, candidates, k):
        if nid == source_id or nid in seen:
            continue
        kind: str | None = None
        if sim >= THRESHOLD_SIMILAR:
            kind = "ähnlich"
        elif sim >= THRESHOLD_EXTEND:
            kind = "erweitert"
        if kind:
            seen.add(nid)
            edges.append(Edge(source=source_id, target=nid, kind=kind, pending=True))
    return edges
