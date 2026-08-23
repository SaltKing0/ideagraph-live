"""Unit-Tests für Memory-Hygiene (V2#2): Status/Probation, Consolidation (Dedup),
Graceful-Degradation-Demotion, invalidated_by-Provenance (V1#1)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ideagraph.brain import Brain, Node, Edge, VALID_STATUS
from ideagraph.brain_engine import BrainEngine
from ideagraph.embedder import HashEmbedder


def make_brain(tmp_path) -> Brain:
    return Brain(str(tmp_path / "brain"), mode="local")


def make_engine(tmp_path) -> BrainEngine:
    return BrainEngine(make_brain(tmp_path), HashEmbedder())


# ---------- Status / Dual-Buffer ----------

def test_node_status_defaults_to_probation():
    n = Node(text="neu")
    assert n.status == "probation"


def test_node_status_roundtrip():
    n = Node(text="x", status="active")
    n2 = Node.from_markdown(n.to_markdown())
    assert n2.status == "active"
    assert "status: active" in n.to_markdown()


def test_valid_status():
    assert VALID_STATUS == ("probation", "active", "tombstone")


def test_ingest_creates_probation_node(tmp_path):
    eng = make_engine(tmp_path)
    node, _, _ = eng.ingest("katze hund tier futter")
    stored = next(n for n in eng.brain.read_nodes() if n.id == node.id)
    assert stored.status == "probation"


# ---------- Consolidation (dedup-basiert) ----------

def test_consolidate_promotes_distinct_probation(tmp_path):
    eng = make_engine(tmp_path)
    eng.ingest("katze hund tier futter")
    eng.ingest("quantenmechanik wellenfunktion schroedinger")
    statuses = {n.status for n in eng.brain.read_nodes()}
    assert statuses == {"probation"}
    report = eng.consolidate()
    assert report["promoted"] == 2 and report["merged"] == 0
    assert {n.status for n in eng.brain.read_nodes()} == {"active"}


def test_consolidate_dedups_cross_probation(tmp_path):
    # Zwei nahezu identische Nodes koexistieren (allow_duplicates) → beide probation.
    # Consolidate muss sie DEDUPIZIEREN (nicht zusammenfassen): einer promoted,
    # der Duplikat wird getombstoned.
    eng = make_engine(tmp_path)
    eng.ingest("katze hund tier futter", source="a")
    eng.ingest("katze hund tier futter", source="b", allow_duplicates=True)
    assert len(eng.brain.read_nodes()) == 2
    report = eng.consolidate()
    assert report["merged"] == 1 and report["promoted"] == 1
    nodes = eng.brain.read_nodes()
    assert len(nodes) == 2
    survivor = next(n for n in nodes if n.status == "active")
    tomb = next(n for n in nodes if n.status == "tombstone")
    assert {"a", "b"} <= set(survivor.sources)


def test_consolidate_empty_is_noop(tmp_path):
    assert make_engine(tmp_path).consolidate() == {"promoted": 0, "merged": 0}


# ---------- Graceful Degradation ----------

def test_demote_forgotten_tombstones_active(tmp_path):
    eng = make_engine(tmp_path)
    eng.ingest("katze hund tier futter")
    eng.consolidate()  # → active
    # level_fn: alles wird tombstone
    count = eng.demote_forgotten(lambda node: "tombstone")
    assert count == 1
    assert all(n.status == "tombstone" for n in eng.brain.read_nodes())


def test_demote_forgotten_keeps_frequent(tmp_path):
    eng = make_engine(tmp_path)
    eng.ingest("katze hund tier futter")
    eng.ingest("quantenmechanik wellenfunktion schroedinger")
    eng.consolidate()  # beide active
    # nur Node mit "katze" wird vergessen
    count = eng.demote_forgotten(lambda n: "tombstone" if "katze" in n.text else "record")
    assert count == 1
    statuses = {n.text: n.status for n in eng.brain.read_nodes()}
    assert statuses["katze hund tier futter"] == "tombstone"
    assert statuses["quantenmechanik wellenfunktion schroedinger"] == "active"


# ---------- invalidated_by-Provenance (V1#1) ----------

def test_invalidate_edge_records_provenance(tmp_path):
    brain = make_brain(tmp_path)
    e1 = Edge(source="a", target="b", kind="erweitert")
    e2 = Edge(source="b", target="c", kind="ähnlich")
    brain.add_edge(e1)
    brain.add_edge(e2)
    invalidated = brain.invalidate_edge(e1.id, by_edge_id=e2.id)
    assert invalidated is not None
    assert invalidated.valid_to is not None
    assert invalidated.invalidated_by == e2.id
    # Roundtrip über die Datei
    reloaded = next(e for e in brain.read_edges() if e.id == e1.id)
    assert reloaded.invalidated_by == e2.id


# ---------- Intent-Edges + Admit-Rule (V2#3) ----------

def test_ingest_contradiction_edge(tmp_path):
    eng = make_engine(tmp_path)
    eng.ingest("Die Erde ist eine Scheibe")
    _, edges, _ = eng.ingest("Die Erde ist keine Scheibe, sondern eine Kugel")
    kinds = {e.kind for e in edges}
    assert "kontradiktorisch" in kinds
    assert all(not e.pending for e in edges if e.kind == "kontradiktorisch")


def test_ingest_supersedes_edge(tmp_path):
    eng = make_engine(tmp_path)
    eng.ingest("API v1 wird verwendet")
    _, edges, _ = eng.ingest("API v2 ersetzt v1")
    assert any(e.kind == "supersedes" for e in edges)


def test_intent_pending_config(tmp_path, monkeypatch):
    # Default (Env ungesetzt): Intent-Edges sind auto-akzeptiert (nicht pending).
    eng = make_engine(tmp_path)
    eng.ingest("Die Erde ist eine Scheibe")
    _, edges, _ = eng.ingest("Die Erde ist keine Scheibe, sondern eine Kugel")
    assert any(e.kind == "kontradiktorisch" and not e.pending for e in edges)
    # Mit IDEAGRAPH_INTENT_PENDING=1: Intent-Edges werden pending (HITL).
    monkeypatch.setenv("IDEAGRAPH_INTENT_PENDING", "1")
    eng2 = make_engine(tmp_path / "b2")  # frischer Brain, sonst Dedupe gegen eng
    eng2.ingest("Die Erde ist eine Scheibe")
    _, edges2, _ = eng2.ingest("Die Erde ist keine Scheibe, sondern eine Kugel")
    assert any(e.kind == "kontradiktorisch" and e.pending for e in edges2)


def test_admit_rule_declared_relations(tmp_path):
    eng = make_engine(tmp_path)
    base, _, _ = eng.ingest("Grundlagen der Quantenmechanik")
    _, edges, _ = eng.ingest(
        "Vertiefung zur Quantenmechanik",
        relations=[(base.text, "continues")],
    )
    assert any(e.kind == "continues" for e in edges)
    assert all(not e.pending for e in edges if e.kind == "continues")
