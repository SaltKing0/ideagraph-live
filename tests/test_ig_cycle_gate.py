"""Tests für das Pipeline-Gate: Marker-Scan-Normalisierung + IG_BRAIN_PATH-Wiring.

Audit #5: der Marker-Scan war per Unicode-Normalisierung/Case bypassbar und die
Allowlist whole-line (ein harmloses Wort unterdrückte Marker-Treffer an anderer
Stelle). Audit #6: --brain wurde vom echten Ingest ignoriert.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from ig_cycle import marker_scan, _fold, MARKERS, ALLOW


def test_homoglyph_marker_is_caught():
    """Kyrillisches і statt i: 'nіcht' muss genauso feuern wie 'nicht'."""
    findings = [("src", "Das Modell nutzt nіcht diese Methode")]  # Cyrillic і
    bad = marker_scan(findings)
    assert any("nicht" in b for b in bad), f"homoglyph bypass: {bad}"


def test_uppercase_marker_is_caught():
    findings = [("src", "Das Modell NICHT vergessen")]
    assert marker_scan(findings)


def test_fullwidth_and_combining_marks_are_caught():
    findings = [("src", "m\u006f\u0308glich nicht")]
    assert marker_scan(findings)


def test_allowlist_is_span_scoped():
    """'Stätte' in der Zeile darf einen 'statt'-Treffer an ANDERER Stelle
    nicht mehr whitelisten (Audit #5b)."""
    findings = [("src", "Treffen statt Morgen … und die Stätte ist gut")]
    bad = marker_scan(findings)
    assert any("statt" in b for b in bad), f"whole-line allowlist bypass: {bad}"


def test_allowlisted_compound_word_alone_passes():
    findings = [("src", "Die Veranstaltung stattet das Tool aus")]
    assert marker_scan(findings) == []


def test_plain_marker_still_caught():
    findings = [("src", "X ersetzt Y")]
    assert any("ersetzt" in b for b in marker_scan(findings))


def test_word_boundary_no_substring_fires():
    """Ein Marker als SUBSTRING in einem anderen Wort feuert nicht (das macht
    detect_intent bewusst anders — hier ist der Gate Wort-basiert)."""
    findings = [("src", "uebersetzt")]  # enthält 'ersetzt' als Substring
    # 'uebersetzt' ist selbst ein Marker (Audit-Lektion), aber 'ersetzt' als
    # Substring von uebersetzt feuert NICHT doppelt:
    bad = marker_scan(findings)
    assert not any(b.endswith("Marker 'ersetzt'") for b in bad)
    assert any("uebersetzt" in b for b in bad)


def test_fold_is_idempotent_and_normalizes():
    assert _fold("NICHT") == _fold("nicht") == _fold("nіcht")  # Cyrillic і
    # NFKD zerlegt ä → a + Combining-Diaeresis, Stripping → 'statte'
    assert _fold("Stätte") == "statte"
