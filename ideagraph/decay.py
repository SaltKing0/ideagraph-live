"""Vergessensstrategie (Roadmap V2#2).

Weibull-Decay auf Retrieval-Frequenz statt hartem Loeschen + Graceful
Degradation Stufenleiter:  record -> summary -> gist -> tombstone.

Reine Funktionen — leicht testbar, keine Dependencies.
"""

from __future__ import annotations

import math

# Stufen der Graceful Degradation, absteigend nach Retention.
DEGRADATION_LADDER = ("record", "summary", "gist", "tombstone")

# Default-Schwellen für die Stufenwahl (Score in [0,1]).
DEGRADATION_THRESHOLDS = (0.6, 0.4, 0.2)


def weibull_decay(age: float, scale: float = 30.0, shape: float = 1.5) -> float:
    """Weibull-Überleben: exp(-(age/scale)^shape) in (0,1].

    Alter in denselben Einheiten wie `scale` (z. B. Tage). Mit zunehmendem Alter
    sinkt der Wert Richtung 0 — ein sanftes Vergessen, kein harter Schnitt.
    """
    if age <= 0:
        return 1.0
    return math.exp(-((age / scale) ** shape))


def retention_from_frequency(retrievals: int, freq_scale: float = 10.0) -> float:
    """Retentions-Anteil aus der Retrieval-Frequenz (sättigend nach oben).

    Je öfter ein Item abgerufen wird, desto mehr bleibt es erhalten —
    dekayt aber nie auf 0 bei mindestens einem Abruf.
    """
    if retrievals <= 0:
        return 0.0
    return 1.0 - math.exp(-retrievals / freq_scale)


def degradation_level(
    score: float,
    thresholds: tuple[float, float, float] = DEGRADATION_THRESHOLDS,
) -> str:
    """Ordnet einen Decay-Score einer Stufe zu (hoch = bleibt, niedrig = stirbt)."""
    if score >= thresholds[0]:
        return "record"
    if score >= thresholds[1]:
        return "summary"
    if score >= thresholds[2]:
        return "gist"
    return "tombstone"


def decay_score(retrievals: int, age: float, freq_scale: float = 10.0,
                age_scale: float = 30.0, shape: float = 1.5) -> float:
    """Kombiniert Retrieval-Frequenz (behält) mit Alter (vergisst) → [0,1]."""
    return retention_from_frequency(retrievals, freq_scale) * weibull_decay(age, age_scale, shape)


def decay_level(retrievals: int, age: float, freq_scale: float = 10.0,
                age_scale: float = 30.0, shape: float = 1.5) -> str:
    """Stufe der Graceful Degradation für ein Item mit (retrievals, age)."""
    return degradation_level(decay_score(retrievals, age, freq_scale, age_scale, shape))
