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
    node1, e1, _ = engine.ingest("Katzen jagen Maeuse nachts", source="agent/test")
    node2, e2, _ = engine.ingest("Katzen schlafen am Tag", source="human")
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
    _, _, _ = engine.ingest("katze hund tier futter")
    _, edges, _ = engine.ingest("katze hund tier spiel")
    kinds = {e.kind for e in edges}
    assert kinds <= {"ähnlich", "erweitert"}


def test_engine_dedupes_exact_duplicate(tmp_path):
    emb = HashEmbedder()
    brain = make_brain(tmp_path)
    engine = BrainEngine(brain, emb)
    node1, _, dup1 = engine.ingest("Katzen jagen Maeuse nachts", source="agent/test")
    node2, edges, dup2 = engine.ingest("Katzen jagen Maeuse nachts", source="human")
    assert not dup1 and dup2
    assert node2.id == node1.id
    assert edges == []
    nodes = brain.read_nodes()
    assert len(nodes) == 1
    assert "human" in nodes[0].sources
    assert "agent/test" in nodes[0].sources


def test_engine_dedupe_ignores_case_and_whitespace(tmp_path):
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    node1, _, _ = engine.ingest("Katzen jagen Maeuse nachts")
    node2, _, dup = engine.ingest("  katzen JAGEN maeuse   NACHTS ")
    assert dup and node2.id == node1.id


def test_engine_dedupe_can_be_disabled(tmp_path):
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    n1, _, _ = engine.ingest("Katzen jagen Maeuse nachts")
    n2, _, dup = engine.ingest("Katzen jagen Maeuse nachts", allow_duplicates=True)
    assert not dup and n2.id != n1.id


def test_engine_no_false_positive_dedupe(tmp_path):
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    engine.ingest("Katzen jagen Maeuse nachts")
    _, _, dup = engine.ingest("Rust Compiler borrow checker lifetime Regeln")
    assert not dup


def test_embedding_cache_hit(tmp_path):
    emb = HashEmbedder()
    brain = make_brain(tmp_path)
    engine = BrainEngine(brain, emb)
    engine.ingest("Katzen jagen Maeuse nachts")
    assert (tmp_path / "brain" / "vectors.jsonl").exists()
    calls = emb.calls if hasattr(emb, "calls") else None
    # zweiter Ingest: alte Node darf nicht neu embeddet werden
    class Counting(HashEmbedder):
        def __init__(self):
            self.n = 0
        def embed(self, text):
            self.n += 1
            return super().embed(text)
    c = Counting()
    e2 = BrainEngine(brain, c)
    e2.ingest("Hunde bellen laute geraeusche")
    # embed-Aufrufe: 1 dup-check neue Node, 0 fuer alte (Cache), 1 cache-fill alte fehlt evtl.
    assert c.n <= 3


def test_edge_suggestion_dedupe(tmp_path):
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    engine.ingest("katze hund tier futter", allow_duplicates=True)
    n2, _, _ = engine.ingest("katze hund tier spiel")
    before = len(engine.brain.read_edges())
    # dritter Ingest aehnlich zu beiden: keine (source,target)-Doppelvorschlaege
    _, edges3, _ = engine.ingest("katze hund tier futter spiel", allow_duplicates=True)
    pairs_before = [(e.source, e.target) for e in engine.brain.read_edges()]
    assert len(pairs_before) == len(set(pairs_before))


def test_engine_link_same_as(tmp_path):
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    n1, _, _ = engine.ingest("Katzen jagen Maeuse")
    n2, _, _ = engine.ingest("Cats hunt mice", allow_duplicates=True)
    edge = engine.link(n1.id, n2.id, "same_as")
    assert edge.kind == "same_as" and not edge.pending
    assert (edge.source, edge.target) in {(e.source, e.target) for e in engine.brain.read_edges()}


def test_engine_link_rejects_unknown_node(tmp_path):
    import pytest
    engine = BrainEngine(make_brain(tmp_path), HashEmbedder())
    n1, _, _ = engine.ingest("Katzen jagen Maeuse")
    with pytest.raises(ValueError):
        engine.link(n1.id, "gibtsnicht", "same_as")


def test_engine_link_rejects_duplicate_edge(tmp_path):
    import pytest
    engine = BrainEngine(make_brain(tmp_path), HashEmbedder())
    n1, _, _ = engine.ingest("Katzen jagen Maeuse")
    n2, _, _ = engine.ingest("Cats hunt mice", allow_duplicates=True)
    engine.link(n1.id, n2.id, "same_as")
    with pytest.raises(ValueError):
        engine.link(n1.id, n2.id, "same_as")


def test_auto_accept_edges(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEAGRAPH_AUTO_ACCEPT", "1")
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    _, edges, _ = engine.ingest("katze hund tier futter")
    _, edges2, _ = engine.ingest("katze hund tier spiel")
    assert all(not e.pending for e in edges2)
    assert not any(e.pending for e in engine.brain.read_edges())
    monkeypatch.delenv("IDEAGRAPH_AUTO_ACCEPT")


def test_default_still_pending(monkeypatch, tmp_path):
    monkeypatch.delenv("IDEAGRAPH_AUTO_ACCEPT", raising=False)
    engine = BrainEngine(make_brain(tmp_path), HashEmbedder())
    engine.ingest("katze hund tier futter")
    _, edges2, _ = engine.ingest("katze hund tier spiel")
    assert all(e.pending for e in edges2)


def test_edge_bi_temporal_fields(tmp_path):
    emb = HashEmbedder()
    engine = BrainEngine(make_brain(tmp_path), emb)
    _, edges, _ = engine.ingest("katze hund tier futter")
    _, edges2, _ = engine.ingest("katze hund tier spiel")
    e = engine.brain.read_edges()[0]
    assert e.valid_from  # gesetzt
    assert e.valid_to is None
    # Invalidieren statt löschen
    invalidated = engine.brain.invalidate_edge(e.id)
    assert invalidated is not None and invalidated.valid_to is not None
    assert any(x.id == e.id and x.valid_to for x in engine.brain.read_edges())


def test_node_type_taxonomy_roundtrip(tmp_path):
    brain = make_brain(tmp_path)
    emb = HashEmbedder()
    engine = BrainEngine(brain, emb)
    node, _, _ = engine.ingest("Wie ingestiere ich Research-Results: ig ingest ...",
                               ntype="procedural")
    stored = next(n for n in brain.read_nodes() if n.id == node.id)
    assert stored.ntype == "procedural"
    assert "type: procedural" in (brain.node_path(node.id)).read_text()


def test_memory_evolution_appends_crossref(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEAGRAPH_AUTO_ACCEPT", "1")
    emb = HashEmbedder()
    brain = make_brain(tmp_path)
    engine = BrainEngine(brain, emb)
    engine.ingest("katze hund tier futter")
    engine.ingest("katze hund tier spiel")  # starke Ähnlichkeit → evolution
    texts = [n.text for n in brain.read_nodes()]
    assert any("evolved" in t for t in texts)
    monkeypatch.delenv("IDEAGRAPH_AUTO_ACCEPT")


def test_no_evolution_without_auto_accept(monkeypatch, tmp_path):
    monkeypatch.delenv("IDEAGRAPH_AUTO_ACCEPT", raising=False)
    engine = BrainEngine(make_brain(tmp_path), HashEmbedder())
    engine.ingest("katze hund tier futter")
    engine.ingest("katze hund tier spiel")
    assert not any("evolved" in n.text for n in engine.brain.read_nodes())
