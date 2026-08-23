"""Edge-Vorschläge: aus den k nächsten Nachbarn werden getypte Vorschläge.

Regeln (bewusst simpel, lernorientiert):
- sim >= 0.75          → "ähnlich"
- 0.45 <= sim < 0.75   → "erweitert" (thematisch verwandt)
- darunter             → kein Vorschlag

"same_as" wird nie automatisch vorgeschlagen — er entsteht manuell
(CLI `link`, Cockpit) für Übersetzungs-/Alias-Paare.

Liefert schlichte Suggestion-Objekte — der Aufrufer entscheidet,
welche Edge-Klasse daraus wird (Store vs. Brain).
"""

from __future__ import annotations

from dataclasses import dataclass
from .similarity import knn

THRESHOLD_SIMILAR = 0.75
THRESHOLD_EXTEND = 0.45


@dataclass
class Suggestion:
    source: str
    target: str
    kind: str


def suggest(source_id: str, query_vec: list[float],
            candidates: dict[str, list[float]], k: int = 3) -> list[Suggestion]:
    out: list[Suggestion] = []
    seen: set[str] = set()
    for nid, sim in knn(query_vec, candidates, k):
        if nid == source_id or nid in seen:
            continue
        if sim >= THRESHOLD_SIMILAR:
            kind = "ähnlich"
        elif sim >= THRESHOLD_EXTEND:
            kind = "erweitert"
        else:
            continue
        seen.add(nid)
        out.append(Suggestion(source=source_id, target=nid, kind=kind))
    return out


# Rückwärtskompatibel für die JSONL-Engine (v0.0.1)
def suggest_edges(source_id: str, query_vec: list[float],
                  candidates: dict[str, list[float]], k: int = 3):
    from .model import Edge
    return [Edge(source=s.source, target=s.target, kind=s.kind, pending=True)
            for s in suggest(source_id, query_vec, candidates, k)]
