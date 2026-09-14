"""Intent-typed edges (Roadmap V2#3, Zettelkasten lesson).

Beyond bare similarity ("similar"/"extends") the engine detects
INTENT between two nodes from signals in the text:

  supersedes      new makes old obsolete        ("API v2 replaces v1")
  contradicts     new denies/opposes old        ("The Earth is NOT flat")
  continues       new continues/builds on old   ("further ... based on")

Heuristic (no NLP dependency), deterministic and testable. Returns None
when no intent is detected — similarity then decides as before.

Audit #35/#36/#51/#61 (fix wave 3): markers match on token boundaries
("versetzt" no longer fires "ersetzt"), the subject check runs
clause-scoped (the marker must share a sentence with a shared content
word — mere presence in the text is not enough), the negation check runs
bidirectionally (new affirms what old denied -> contradicts too), and
the marker sets are fully bilingual.
"""

from __future__ import annotations

import re

# Marker als Token-Folgen (lowercase). Matching ist Token-basiert: ein Marker
# passt nur, wenn seine Token als FOLGE im Token-Stream stehen — "versetzt"
# (Tokens: [versetzt]) matcht "ersetzt" nicht mehr, "findet statt" (Tokens
# [findet, statt]) matcht den supersedes-Marker "statt" weiterhin, weil er
# dort wirklich als eigenes Wort auftritt (aber nur im selben Satz wie das
# Subjekt — siehe _clause_hits).
# Zweisprachig (Audit #61): jedes Set deckt DE und EN ab.
SUPERSEDE_MARKERS: tuple[tuple[str, ...], ...] = (
    ("ersetzt",), ("ersetzt", "durch"), ("ersatz",),
    ("ablöst",), ("löst", "ab"), ("abgelöst",),
    ("supersedes",), ("superseded",), ("replaces",), ("replaced", "by"),
    ("obsolet",), ("obsolete",), ("deprecated",),
    ("statt",), ("anstelle", "von"), ("instead", "of"), ("replaces",),
)
CONTRADICT_MARKERS: tuple[tuple[str, ...], ...] = (
    ("ist", "nicht"), ("nicht", "mehr"), ("keineswegs",),
    ("widerspricht",), ("widersprochen",),
    ("keine",), ("kein",), ("niemals",), ("nie",),
    ("ist", "falsch"), ("falsch",), ("falsche",),
    ("is", "not"), ("no", "longer"), ("never",), ("not", "true"),
    ("false",), ("wrong",), ("contradicts",),
)
CONTINUE_MARKERS: tuple[tuple[str, ...], ...] = (
    ("setzt", "fort"), ("basiert", "auf"), ("aufbauend",),
    ("weiterentwicklung",), ("weiterentwickelt",), ("verfeinert",),
    ("erweitert", "um"), ("fortgeführt",),
    ("builds", "on"), ("based", "on"), ("extends",), ("extends", "with"),
    ("continues",), ("continued",), ("refines",), ("follows", "from"),
)

# Priority on multiple hits (audit #51): supersedes > contradicts
# > continues — dokumentiert und deterministisch; die satzenlage Subjekt-
# Prüfung disambiguiert die meisten Doppeltreffer bereits.
_PRIORITY = ("supersedes", "contradicts", "continues")

_MARKER_TO_INTENT: dict[tuple[str, ...], str] = {}
for _m in SUPERSEDE_MARKERS:
    _MARKER_TO_INTENT[_m] = "supersedes"
for _m in CONTRADICT_MARKERS:
    _MARKER_TO_INTENT[_m] = "contradicts"
for _m in CONTINUE_MARKERS:
    _MARKER_TO_INTENT[_m] = "continues"

_WORD_RE = re.compile(r"[a-zäöüß0-9]+")

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


def _tokens(text: str) -> list[str]:
    """Token-Stream: lowercase, Interpunktion getrennt (Audit #36: "Erde," war
    vorher ein anderes Token als "Erde")."""
    return _WORD_RE.findall(text.lower())


def _content_words(text: str) -> set[str]:
    return {w for w in _tokens(text) if len(w) >= 3 and w not in _STOPWORDS}


def _clauses(text: str) -> list[list[str]]:
    """Satz/Teilsatz-Grenzen: . ! ? ; , : und Zeilenumbrüche trennen."""
    parts = re.split(r"[.!?;,:()\[\]\"\']|\n+", text.lower())
    return [_tokens(p) for p in parts if _tokens(p)]


def _marker_hits(tokens: list[str], markers: tuple[tuple[str, ...], ...]) -> list[tuple[str, ...]]:
    """Marker, die als zusammenhängende Token-Folge vorkommen."""
    hits = []
    n = len(tokens)
    for m in markers:
        L = len(m)
        for i in range(n - L + 1):
            if tokens[i:i + L] == list(m):
                hits.append(m)
                break
    return hits


# Nomen-Negations-/Ersetzungs-Marker: hier ist das negierte/ersetzte Ding das
# OBJEKT des Markers — es muss als geteiltes Inhaltswort KURZ NACH dem Marker
# stehen. "keine Zeit für Review" negiert "Zeit", nicht "Review" (Audit #35);
# "findet statt" hat kein Objekt nach "statt" (stattfinden-Verb, kein supersedes).
_OBJECT_MARKERS = frozenset(("keine", "kein", "nie", "niemals", "statt", "falsch",
                             "falsche", "no", "never", "false", "wrong"))


def _marker_object_shared(clause: list[str], marker: tuple[str, ...], subjects: set[str]) -> bool:
    if marker[0] not in _OBJECT_MARKERS:
        return True  # verbale Marker: Subjekt-im-Satz-Prüfung genügt
    # Position des Marker-Endes suchen; ein geteiltes Inhaltswort innerhalb der
    # nächsten 2 Tokens macht die Negation zum Gegenstand ("keine Scheibe" ✓,
    # "keine Zeit für Review" ✗ — Review steht an Position +3 und ist nicht
    # das Negierte). Fenster ist positional (Artikel/Adjektive dazwischen ok).
    n = len(clause)
    for i in range(n - len(marker) + 1):
        if clause[i:i + len(marker)] == list(marker):
            window = clause[i + len(marker):i + len(marker) + 2]
            if set(window) & subjects:
                return True
    return False


def _clause_hits(clauses: list[list[str]], markers: tuple[tuple[str, ...], ...],
                 subjects: set[str]) -> bool:
    """True, wenn ein Marker im selben Satz/Teilsatz wie ein Subjekt-Inhaltswort steht.

    Audit #35: bloße Marker-Anwesenheit im Text feuerte gegen JEDE verwandte
    Node ("Der Mitarbeiter wird versetzt" → supersedes wegen 'ersetzt'-Substring
    in 'versetzt' + geteilte Domänenwörter). Jetzt muss der Marker im selben
    Satz wie ein geteiltes Inhaltswort stehen — und bei Objekt-Markern (keine/
    kein/nie/statt/falsch) muss das negierte/ersetzte Objekt selbst geteilt sein."""
    for clause in clauses:
        if not (_content_words(" ".join(clause)) & subjects):
            continue
        hits = _marker_hits(clause, markers)
        if any(_marker_object_shared(clause, m, subjects) for m in hits):
            return True
    return False


def detect_intent(new_text: str, old_text: str) -> str | None:
    """Intent zwischen neuer und bestehender Node, oder None.

    `new_text` ist die neu ingestierte Aussage, `old_text` die bestehende.
    Alle drei Intents verlangen, dass beide über denselben Gegenstand
    sprechen (geteilte Inhaltswörter) UND dass der Marker im selben Satz
    wie ein geteiltes Inhaltswort steht (Audit #35).

    Audit #36 (beidseitige Negation): verneint ALT den Gegenstand und bejaht
    NEW affirms it (or vice versa), that is also contradicts — before
    lieferte new-affirms-what-old-denies None.
    """
    new_subjects = _content_words(new_text)
    shared = new_subjects & _content_words(old_text)
    if not shared:
        return None

    new_clauses = _clauses(new_text)
    old_clauses = _clauses(old_text)

    hits: dict[str, bool] = {}
    for intent, markers in (
        ("supersedes", SUPERSEDE_MARKERS),
        ("contradicts", CONTRADICT_MARKERS),
        ("continues", CONTINUE_MARKERS),
    ):
        hits[intent] = (
            _clause_hits(new_clauses, markers, shared)
            or _clause_hits(old_clauses, markers, shared)
        )

    # Beidseitige Negation (Audit #36): alt verneint, neu bejaht denselben
    # Gegenstand ohne Verneinung → Widerspruch zwischen den Aussagen.
    if not hits["contradicts"]:
        old_denies = _clause_hits(old_clauses, CONTRADICT_MARKERS, shared)
        new_denies = _clause_hits(new_clauses, CONTRADICT_MARKERS, shared)
        if old_denies and not new_denies:
            hits["contradicts"] = True

    for intent in _PRIORITY:
        if hits[intent]:
            return intent
    return None
