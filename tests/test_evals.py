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
    verify_end_state,
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
        b, EvalOracle(edges=[EdgeExpectation("alpha", "beta", "erweitert")])
    )
    assert any("edge missing" in f for f in failures)


def test_verify_detects_unexpected_edge(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="alpha"))
    b.write_node(Node(id="b", text="beta"))
    b.add_edge(Edge(source="a", target="b", kind="erweitert"))
    failures = verify_end_state(b, EvalOracle(no_edge=[EdgeExpectation("alpha", "beta", "*")]))
    assert any("unexpected edge" in f for f in failures)


def test_verify_wildcard_kind_matches_any_edge(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="alpha"))
    b.write_node(Node(id="b", text="beta"))
    b.add_edge(Edge(source="a", target="b", kind="ähnlich"))
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
    assert ROADMAP_CASES, "Roadmap-Fälle dürfen nicht leer sein"
    ids = [t.id for t in ROADMAP_CASES]
    assert len(ids) == len(set(ids)), "Roadmap-Fälle müssen eindeutige ids haben"
    assert all(t.id.startswith("roadmap-") for t in ROADMAP_CASES)
    assert GOLDEN_SET, "Golden-Set darf nicht leer sein"


def test_roadmap_cases_are_not_yet_green(tmp_path):
    """Solange ein Roadmap-Feature nicht implementiert ist, schlägt sein Fall fehl.

    Sobald wir ein Feature umsetzen, wandert sein Fall ins GOLDEN_SET — das ist
    der messbare Fortschritt. Hier prüfen wir nur, dass noch NICHT alles grün ist
    (d. h. es gibt echte offene Arbeit), nicht welcher Fall konkret fehlschlägt.
    """
    counter = [0]

    def factory():
        counter[0] += 1
        d = tmp_path / f"r{counter[0]}"
        return BrainEngine(Brain(str(d), mode="local"), HashEmbedder())

    results = [run_eval(t, factory) for t in ROADMAP_CASES]
    assert any(not r.passed for r in results), (
        "Alle Roadmap-Fälle sind grün — verschiebe sie ins GOLDEN_SET!"
    )
