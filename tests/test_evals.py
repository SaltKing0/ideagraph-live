"""Tests für den Eval-Layer: End-State-Verification, pass^k, Golden-Set.

Das Golden-Set ist die MESS-BASELINE: Es muss auf dem aktuellen Engine-Stand
grün sein. Jede spätere Roadmap-Änderung wird gegen diese Fälle geprüft.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ideagraph.brain import Brain, Node, Edge
from ideagraph.brain_engine import BrainEngine
from ideagraph.embedder import HashEmbedder
from ideagraph.evals import (
    EvalOracle,
    EdgeExpectation,
    RetrievalExpectation,
    verify_end_state,
    verify_retrieval,
    run_eval,
    GOLDEN_SET,
    ROADMAP_CASES,
)


# ---------------------------------------------------------------------------
# Harness-Unit-Tests: verify_end_state + pass^k
# ---------------------------------------------------------------------------

def _brain(tmp_path) -> Brain:
    return Brain(str(tmp_path / "brain"), mode="local")


def test_verify_detects_missing_node(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="vorhanden"))
    failures = verify_end_state(b, EvalOracle(nodes_present=["vorhanden", "fehlt"]))
    assert any("fehlt" in f for f in failures)
    assert not any("vorhanden" in f for f in failures)


def test_verify_detects_wrong_count(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="x"))
    b.write_node(Node(id="b", text="y"))
    failures = verify_end_state(b, EvalOracle(node_count=1))
    assert any("node_count" in f for f in failures)


def test_verify_detects_missing_source(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="x", source="human"))
    failures = verify_end_state(b, EvalOracle(duplicate_merged=[("x", ["human", "agent"])]))
    assert any("agent" in f for f in failures)


def test_verify_detects_missing_edge(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="alpha"))
    b.write_node(Node(id="b", text="beta"))
    failures = verify_end_state(
        b, EvalOracle(edges=[EdgeExpectation("alpha", "beta", "extends")])
    )
    assert any("edge missing" in f for f in failures)


def test_verify_detects_unexpected_edge(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="alpha"))
    b.write_node(Node(id="b", text="beta"))
    b.add_edge(Edge(source="a", target="b", kind="extends"))
    failures = verify_end_state(b, EvalOracle(no_edge=[EdgeExpectation("alpha", "beta", "*")]))
    assert any("unexpected edge" in f for f in failures)


def test_verify_retrieval_detects_missing_hit(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="katze hund tier futter"))
    b.write_node(Node(id="b", text="quantenmechanik wellenfunktion schroedinger"))
    engine = BrainEngine(b, HashEmbedder())
    # Erwartung stimmt → keine Fehler
    ok = verify_retrieval(engine, [RetrievalExpectation(query="katze futter", top=1, includes=["katze hund tier futter"], excludes=["quantenmechanik wellenfunktion schroedinger"])])
    assert ok == []
    # Erwartung stimmt nicht → Fehler
    bad = verify_retrieval(engine, [RetrievalExpectation(query="katze futter", top=1, includes=["quantenmechanik wellenfunktion schroedinger"])])
    assert any("should hit" in f for f in bad)


def test_verify_wildcard_kind_matches_any_edge(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="alpha"))
    b.write_node(Node(id="b", text="beta"))
    b.add_edge(Edge(source="a", target="b", kind="similar"))
    assert verify_end_state(b, EvalOracle(edges=[EdgeExpectation("alpha", "beta", "*")])) == []


def test_pass_k_runs_each_scenario_fresh(tmp_path):
    # Zähler für frische Brain-Verzeichnisse je Lauf
    counter = [0]

    def factory():
        counter[0] += 1
        d = tmp_path / f"b{counter[0]}"
        return BrainEngine(Brain(str(d), mode="local"), HashEmbedder())

    task = GOLDEN_SET[0]  # dup-exact
    result = run_eval(task, factory, k=2)
    assert result.passed
    assert result.runs == 2
    assert counter[0] == 2  # zwei frische Brains erzeugt


# ---------------------------------------------------------------------------
# Golden-Set — die Mess-Baseline (MUSS grün sein)
# ---------------------------------------------------------------------------

def test_golden_set_all_pass(tmp_path):
    counter = [0]

    def factory():
        counter[0] += 1
        d = tmp_path / f"g{counter[0]}"
        return BrainEngine(Brain(str(d), mode="local"), HashEmbedder())

    failures = []
    for task in GOLDEN_SET:
        res = run_eval(task, factory)
        if not res.passed:
            failures.append(f"[{task.id}] {res.failures}")
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# Roadmap-Fälle — registrierte Spezifikation für kommende Features
# ---------------------------------------------------------------------------

def test_roadmap_cases_registered():
    # Leere ROADMAP_CASES = alle V2-Features sind umgesetzt (im GOLDEN_SET).
    # Wenn Einträge existieren, brauchen sie eindeutige, roadmap-*-ids.
    ids = [t.id for t in ROADMAP_CASES]
    assert len(ids) == len(set(ids)), "Roadmap-Fälle müssen eindeutige ids haben"
    assert all(t.id.startswith("roadmap-") for t in ROADMAP_CASES)
    assert GOLDEN_SET, "Golden-Set darf nicht leer sein"


def test_roadmap_cases_are_not_yet_green(tmp_path):
    """Solange ein Roadmap-Feature nicht implementiert ist, schlägt sein Fall fehl.

    Audit #52: sobald ROADMAP_CASES leer ist, war dieser Test still vacuous —
    das Flip-Gate hätte sich silently deaktiviert. Jetzt erzwingt der Test die
    bewusste Entscheidung: eine leere ROADMAP_CASES ist nur mit einem
    Status-Marker-File legitim (der die letzte Flip-Aktion dokumentiert), sonst
    FAIL mit Anleitung.
    """
    marker = Path(__file__).resolve().parent.parent / "ROADMAP_CASES_EMPTY"
    if not ROADMAP_CASES:
        assert marker.exists(), (
            "ROADMAP_CASES ist leer: entweder eine neue roadmap-* EvalTask in "
            "ideagraph/evals.py registrieren, oder die bewusste Entscheidung "
            f"dokumentieren: touch {marker.name} (mit Datum + Grund im File)."
        )
        return  # dokumentiert leer
    counter = [0]

    def factory():
        counter[0] += 1
        d = tmp_path / f"r{counter[0]}"
        return BrainEngine(Brain(str(d), mode="local"), HashEmbedder())

    results = [run_eval(t, factory) for t in ROADMAP_CASES]
    assert any(not r.passed for r in results), (
        "Alle Roadmap-Fälle sind grün — verschiebe sie ins GOLDEN_SET!"
    )


# ---------------------------------------------------------------------------
# Audit #27: oracle matching correctness
# ---------------------------------------------------------------------------

def test_find_node_by_text_exact_beats_prefix(tmp_path):
    """#27a: oracle texts that are prefixes of each other resolve correctly."""
    from ideagraph.evals import find_node_by_text
    b = _brain(tmp_path)
    b.write_node(Node(id="short", text="Agent memory"))
    b.write_node(Node(id="long", text="Agent memory consolidation improves recall"))
    # exact match wins even though the prefix node comes first
    assert find_node_by_text(b, "Agent memory consolidation").id == "long"
    assert find_node_by_text(b, "Agent memory").id == "short"


def test_find_node_by_text_prefix_prefers_original(tmp_path):
    """#27a: after evolution appends a suffix, the original (shortest) wins."""
    from ideagraph.evals import find_node_by_text
    b = _brain(tmp_path)
    b.write_node(Node(id="evolved", text="Agent memory [evolved from abc123]"))
    b.write_node(Node(id="other", text="Agent memory consolidation improves recall"))
    n = find_node_by_text(b, "Agent memory")
    assert n.id == "evolved"  # shortest prefix, not first-hit order


def test_no_edge_ignores_invalidated_and_foreign_kind(tmp_path):
    """#27b: no_edge mirrors the positive path — valid_to + kind aware."""
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="alpha node"))
    b.write_node(Node(id="b", text="beta node"))
    import time
    dead = Edge(source="a", target="b", kind="similar", pending=False)
    dead.valid_to = time.time()  # invalidated
    b.write_edges([dead])
    # an invalidated edge is NOT an unexpected edge
    assert verify_end_state(b, EvalOracle(
        no_edge=[EdgeExpectation("alpha node", "beta node", "similar")])) == []
    # a live edge of a DIFFERENT kind is not a violation of a specific kind
    b.write_edges([Edge(source="a", target="b", kind="extends", pending=False)])
    assert verify_end_state(b, EvalOracle(
        no_edge=[EdgeExpectation("alpha node", "beta node", "similar")])) == []
    # but a live edge of the SAME kind IS
    b.write_edges([Edge(source="a", target="b", kind="similar", pending=False)])
    failures = verify_end_state(b, EvalOracle(
        no_edge=[EdgeExpectation("alpha node", "beta node", "similar")]))
    assert any("unexpected edge" in f for f in failures)
