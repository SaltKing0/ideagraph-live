"""Unit-Tests für Intent-getypte Edges (V2#3): supersedes / kontradiktorisch / continues."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ideagraph.intent import detect_intent


def test_supersedes_replacement_marker():
    assert detect_intent("API v2 ersetzt v1", "API v1 wird verwendet") == "supersedes"


def test_supersedes_requires_shared_subject():
    # Marker vorhanden, aber über ein anderes Thema → kein supersedes.
    # (Regression: ohne diese Prüfung markierte eine Node mit Marker-Wort
    #  JEDE bestehende Node als supersedes.)
    assert detect_intent("API v2 ersetzt v1", "Die Erde ist eine Scheibe") is None


def test_contradiction_negation():
    assert (
        detect_intent(
            "Die Erde ist keine Scheibe, sondern eine Kugel",
            "Die Erde ist eine Scheibe",
        )
        == "kontradiktorisch"
    )


def test_contradiction_requires_shared_subject():
    # Negation vorhanden, aber über ein anderes Thema → kein Kontradiktorisch
    assert detect_intent("Katzen sind keine Hunde", "Die Erde ist eine Scheibe") is None


def test_continues_builds_on():
    assert detect_intent(
        "Vertiefung basiert auf der bisherigen Arbeit",
        "Arbeit an X",
    ) == "continues"


def test_no_intent_for_unrelated():
    assert detect_intent("quantenmechanik wellenfunktion", "katze hund tier") is None


def test_no_intent_for_plain_similarity():
    # Ohne Intent-Signal → None (Similarity entscheidet weiterhin)
    assert detect_intent("katze hund tier futter", "katze hund tier spiel") is None
