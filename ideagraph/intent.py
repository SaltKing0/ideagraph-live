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


# Gemeine Funktions-/Stoppwörter (DE + EN), die KEINEN Themenüberlapp anzeigen.
# Ohne Filter wäre `shared` fast immer true (die/der/und/ist… in jedem Text),
# wodurch die Intent-Subjekt-Prüfung wirkungslos würde.
_STOPWORDS = frozenset(
    """
    die der das und ist ein eine einer eines mit von für auf den dem aus bei
    als wie nur auch sich nicht keine kein sind wird werden wurde sein ihre
    ihren ihrer diesem diese dieses dieser gegen über unter zwischen ohne weil
    dass durch zum zur im am in an wir ich du er sie es war hat habe haben
    dann wenn so aber oder noch nach vor hier da bitte würde können sollen
    muss worden indem obwohl deshalb trotz außer sowohl sowie bspw z.b bzw
    the and is are with for on of a an to in not no this that but or as was
    were been has have it its be been can will would should must shall may
    """.split()
)


def _content_words(text: str) -> set[str]:
    return {w for w in text.split() if len(w) >= 3 and w not in _STOPWORDS}


def detect_intent(new_text: str, old_text: str) -> str | None:
    """Intent zwischen neuer und bestehender Node, oder None.

    `new_text` ist die neu ingestierte Aussage, `old_text` die bestehende.
    Alle drei Intents verlangen, dass beide über denselben Gegenstand
    sprechen (geteilte Inhaltswörter), um Fehltreffer zu vermeiden — auch
    supersedes: ein bloßes Marker-Wort (z.B. "ersetzt", "supersedes") darf
    eine Node nicht gegen JEDE bestehende Node als Nachfolger markieren.
    """
    nt = " " + new_text.lower() + " "
    ot = " " + old_text.lower() + " "
    shared = bool(_content_words(nt) & _content_words(ot))

    if shared and any(m in nt for m in SUPERSEDE_MARKERS):
        return "supersedes"
    if shared and any(m in nt for m in CONTRADICT_MARKERS):
        return "kontradiktorisch"
    if shared and any(m in nt for m in CONTINUE_MARKERS):
        return "continues"
    return None
