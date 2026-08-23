"""Edge-Vorschläge: aus den k nächsten Nachbarn werden getypte Vorschläge.

Regeln (V2#3 — Confidence-Bänder statt nur Schwellen):
- sim >= 0.95            → "ähnlich", AUTO-ACCEPT (pending=False), confidence=sim
- 0.75 <= sim < 0.95     → "ähnlich", pending
- 0.45 <= sim < 0.75     → "erweitert", pending
- sim < 0.45             → kein Vorschlag

Jeder Vorschlag trägt einen confidence (die Kosinus-Ähnlichkeit). Der Aufrufer
(BrainEngine) entscheidet anhand des Bands + Env-Override, ob pending bleibt.

"same_as" wird nie automatisch vorgeschlagen — er entsteht manuell
(CLI `link`, Cockpit) für Übersetzungs-/Alias-Paare.
"""

from __future__ import annotations

from dataclasses import dataclass

from .similarity import knn

THRESHOLD_SIMILAR = 0.75
THRESHOLD_EXTEND = 0.45
AUTO_ACCEPT_CONFIDENCE = 0.95


@dataclass
class Suggestion:
    source: str
    target: str
    kind: str
    confidence: float = 0.0


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
        out.append(Suggestion(source=source_id, target=nid, kind=kind, confidence=sim))
    return out


def is_auto_accept(confidence: float) -> bool:
    """Confidence-Band: >=0.95 wird ohne HITL akzeptiert."""
    return confidence >= AUTO_ACCEPT_CONFIDENCE


# Rückwärtskompatibel für die JSONL-Engine (v0.0.1)
def suggest_edges(source_id: str, query_vec: list[float],
                  candidates: dict[str, list[float]], k: int = 3):
    from .model import Edge
    return [Edge(source=s.source, target=s.target, kind=s.kind, pending=True)
            for s in suggest(source_id, query_vec, candidates, k)]
