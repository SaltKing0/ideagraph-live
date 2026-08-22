"""Tests für Similarity + Edge-Vorschlag (HashEmbedder — deterministisch, ohne Netz)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ideagraph.similarity import cosine, knn
from ideagraph.embedder import HashEmbedder
from ideagraph.suggester import suggest_edges
from ideagraph.store import Store
from ideagraph.engine import Engine


def test_cosine_identical():
    v = [1.0, 2.0, 3.0]
    assert abs(cosine(v, v) - 1.0) < 1e-9


def test_cosine_orthogonal():
    assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9


def test_cosine_zero_vector():
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_knn_order_and_k():
    cands = {"a": [1.0, 0.0], "b": [0.9, 0.1], "c": [0.0, 1.0]}
    result = knn([1.0, 0.0], cands, k=2)
    assert len(result) == 2
    assert result[0][0] == "a"
    assert result[1][0] == "b"


emb = HashEmbedder()


def test_hash_embedder_deterministic():
    assert emb.embed("hallo welt") == emb.embed("hallo welt")


def test_suggest_similar_edge():
    vec_a = emb.embed("katze hund tier futter")
    candidates = {"b": emb.embed("katze hund tier spiel")}
    edges = suggest_edges("a", vec_a, candidates)
    assert len(edges) == 1
    assert edges[0].kind == "ähnlich"
    assert edges[0].source == "a" and edges[0].target == "b"
    assert edges[0].pending is True


def test_suggest_extend_edge():
    # Teilweise Wortüberlappung → "erweitert"-Bereich
    vec_a = emb.embed("katze hund tier futter")
    candidates = {"c": emb.embed("katze hund auto straße futter katze hund")}
    edges = suggest_edges("a", vec_a, candidates)
    kinds = {e.kind for e in edges}
    assert kinds <= {"ähnlich", "erweitert"}
    assert all(e.pending for e in edges)


def test_suggest_no_self_edge():
    vec_a = emb.embed("irgendein text hier")
    candidates = {"a": vec_a}
    assert suggest_edges("a", vec_a, candidates) == []


def test_engine_ingest_creates_node_and_pending(tmp_path):
    store = Store(tmp_path / "data.jsonl")
    engine = Engine(store, HashEmbedder())
    node1, _ = engine.ingest("katze hund tier futter")
    node2, edges = engine.ingest("katze hund tier spiel")
    assert len(store.nodes) == 2
    assert all(e.pending for e in edges)


def test_store_resolve_accept(tmp_path):
    from ideagraph.model import Edge
    store = Store(tmp_path / "data.jsonl")
    edge = Edge(source="a", target="b", kind="ähnlich")
    store.add_edge(edge)
    resolved = store.resolve_edge(edge.id, accept=True)
    assert resolved is not None and resolved.pending is False


def test_store_resolve_reject(tmp_path):
    from ideagraph.model import Edge
    store = Store(tmp_path / "data.jsonl")
    edge = Edge(source="a", target="b", kind="erweitert")
    store.add_edge(edge)
    eid = edge.id
    resolved = store.resolve_edge(eid, accept=False)
    assert resolved is None or eid not in {e.id for e in store.edges}


def test_empty_text_raises(tmp_path):
    engine = Engine(Store(tmp_path / "d.jsonl"), HashEmbedder())
    import pytest
    with pytest.raises(ValueError):
        engine.ingest("   ")
