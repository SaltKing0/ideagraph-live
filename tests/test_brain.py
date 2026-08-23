"""Tests für den Brain-Layer: Markdown-Format, Edges, Engine-Loop.

mode="local" — reines Dateisystem, kein Git, kein Netz.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ideagraph.brain import Brain, Node, Edge
from ideagraph.brain_engine import BrainEngine
from ideagraph.embedder import HashEmbedder


def make_brain(tmp_path):
    return Brain(str(tmp_path / "brain"), mode="local")


# ---------- Markdown-Roundtrip ----------

def test_node_markdown_roundtrip():
    n = Node(text="Katzen jagen Maeuse", source="agent/bot", tags=["tiere", "test"])
    raw = n.to_markdown()
    n2 = Node.from_markdown(raw)
    assert n2.id == n.id and n2.text == n.text and n2.source == "agent/bot"
    assert n2.tags == ["tiere", "test"]


def test_node_roundtrip_umlauts():
    n = Node(text="Ideen mit Ümläuten und ß")
    n2 = Node.from_markdown(n.to_markdown())
    assert n2.text == "Ideen mit Ümläuten und ß"


def test_node_from_markdown_rejects_plain_text():
    import pytest
    with pytest.raises(ValueError):
        Node.from_markdown("kein frontmatter")


# ---------- Brain-FS ----------

def test_write_and_read_nodes(tmp_path):
    brain = make_brain(tmp_path)
    brain.write_node(Node(id="aaa", text="Erste Idee"))
    brain.write_node(Node(id="bbb", text="Zweite Idee"))
    nodes = brain.read_nodes()
    assert [n.id for n in nodes] == ["aaa", "bbb"]


def test_edges_roundtrip_and_resolve(tmp_path):
    brain = make_brain(tmp_path)
    e = Edge(source="a", target="b", kind="ähnlich")
    brain.add_edge(e)
    resolved = brain.resolve_edge(e.id, accept=True)
    assert resolved is not None and resolved.pending is False
    assert all(not x.pending for x in brain.read_edges())


def test_edge_reject_removes(tmp_path):
    brain = make_brain(tmp_path)
    e = Edge(source="a", target="b", kind="erweitert")
    brain.add_edge(e)
    brain.resolve_edge(e.id, accept=False)
    assert brain.read_edges() == []


def test_resolve_unknown_returns_none(tmp_path):
    brain = make_brain(tmp_path)
    assert brain.resolve_edge("gibtsnicht", accept=True) is None


def test_graph_state_shape(tmp_path):
    brain = make_brain(tmp_path)
    brain.write_node(Node(id="a", text="x"))
    brain.add_edge(Edge(source="a", target="a", kind="ähnlich"))
    state = brain.graph_state()
    assert len(state["nodes"]) == 1 and len(state["edges"]) == 1


def test_index_rebuild(tmp_path):
    brain = make_brain(tmp_path)
    brain.write_node(Node(id="a", text="Eine tolle Idee"))
    brain.rebuild_index()
    index = (brain.path / "INDEX.md").read_text(encoding="utf-8")
    assert "nodes/a.md" in index and "Eine tolle Idee" in index


# ---------- Engine-Loop ----------

def test_engine_ingest_creates_files(tmp_path):
    brain = make_brain(tmp_path)
    engine = BrainEngine(brain, HashEmbedder())
    node1, e1 = engine.ingest("Katzen jagen Maeuse nachts", source="agent/test")
    node2, e2 = engine.ingest("Katzen schlafen am Tag", source="human")
    assert (brain.path / "nodes" / f"{node1.id}.md").exists()
    assert (brain.path / "nodes" / f"{node2.id}.md").exists()
    for edge in e1 + e2:
        assert edge.pending is True
        assert any(x.id == edge.id for x in brain.read_edges())


def test_engine_empty_raises(tmp_path):
    import pytest
    engine = BrainEngine(make_brain(tmp_path), HashEmbedder())
    with pytest.raises(ValueError):
        engine.ingest("   ")


def test_engine_suggests_similar_kind(tmp_path):
    emb = HashEmbedder()
    brain = make_brain(tmp_path)
    engine = BrainEngine(brain, emb)
    _, _ = engine.ingest("katze hund tier futter")
    _, edges = engine.ingest("katze hund tier spiel")
    kinds = {e.kind for e in edges}
    assert kinds <= {"ähnlich", "erweitert"}
