"""Intent-getypte Edges (Roadmap V2#3, Zettelkasten-Lektion).

Statt nur bare similarity ("ähnlich"/"erweitert") erkennt die Engine die
INTENTION zwischen zwei Nodes anhand von Signalen im Text:

  supersedes      neu ersetzt/obsolet macht alt   ("API v2 ersetzt v1")
  kontradiktorisch neu verneint/opponiert alt      ("Die Erde ist KEINE Scheibe")
  continues       neu führt alt fort / baut auf    ("weiter ... basiert auf")

Heuristisch (keine NLP-Dependency), deterministisch und testbar. Liefert None,
wenn kein Intent erkannt wird — dann entscheidet weiterhin die Similarity.
"""

from __future__ import annotations

# Marker, sortiert nach Spezifität (supersedes > kontradiktorisch > continues).
SUPERSEDE_MARKERS = (
    "ersetzt durch", "ersetzt", "ablösen", "ablöst", "supersedes",
    "obsolet", "statt", "anstelle von",
)
CONTRADICT_MARKERS = (
    "ist nicht", "keineswegs", "widerspricht", "nicht mehr", "keine", "kein",
    "niemals", "ist falsch", "sondern", "falsch",
)
CONTINUE_MARKERS = (
    "setzt fort", "basiert auf", "aufbauend", "weiterentwicklung",
    "weiterentwickelt", "verfeinert", "erweitert um",
)


def _content_words(text: str) -> set[str]:
    return {w for w in text.split() if len(w) > 3}


def detect_intent(new_text: str, old_text: str) -> str | None:
    """Intent zwischen neuer und bestehender Node, oder None.

    `new_text` ist die neu ingestierte Aussage, `old_text` die bestehende.
    Kontradiktorisch/continues verlangen, dass beide über denselben Gegenstand
    sprechen (geteilte Inhaltswörter), um Fehltreffer zu vermeiden.
    """
    nt = " " + new_text.lower() + " "
    ot = " " + old_text.lower() + " "
    shared = bool(_content_words(nt) & _content_words(ot))

    if any(m in nt for m in SUPERSEDE_MARKERS):
        return "supersedes"
    if shared and any(m in nt for m in CONTRADICT_MARKERS):
        return "kontradiktorisch"
    if shared and any(m in nt for m in CONTINUE_MARKERS):
        return "continues"
    return None
