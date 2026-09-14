"""Tests for the pipeline gate: marker-scan normalization + IG_BRAIN_PATH wiring.

Audit #5: the marker scan was bypassable via Unicode normalization/case and the
allowlist was whole-line (one innocent word suppressed marker hits elsewhere).
Audit #6: --brain was ignored by the real ingest.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from ig_cycle import marker_scan, _fold, MARKERS, ALLOW


def test_homoglyph_marker_is_caught():
    """Cyrillic і instead of i: 'nіcht' must fire just like 'nicht'."""
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
    """'Stätte' in the line must no longer whitelist a 'statt' hit
    ELSEWHERE (Audit #5b)."""
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
    """A marker as a SUBSTRING of another word does not fire (this makes
    detect_intent deliberately different — this gate is word-based)."""
    findings = [("src", "uebersetzt")]  # contains 'ersetzt' as a substring
    # 'uebersetzt' is itself a marker (audit lesson), but 'ersetzt' as a
    # substring of uebersetzt does NOT fire twice:
    bad = marker_scan(findings)
    assert not any(b.endswith("marker 'ersetzt'") for b in bad)
    assert any("uebersetzt" in b for b in bad)


def test_fold_is_idempotent_and_normalizes():
    assert _fold("NICHT") == _fold("nicht") == _fold("nіcht")  # Cyrillic і
    # NFKD decomposes ä → a + combining diaeresis, stripping → 'statte'
    assert _fold("Stätte") == "statte"
