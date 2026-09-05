"""Tests für die Near-Duplikat-Konsolidierung (`ig merge`).

Definieren das erwartete Verhalten von merge_nodes: Kanten-Umleitung,
Dedup, Selbstschleifen-Entfernung, Text-Zusammenführung, Vektor-Cleanup,
INDEX-Rebuild — bevor weiter darauf aufgebaut wird.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ideagraph.brain import Brain, Node, Edge
from ideagraph.merge import merge_nodes


def _brain(tmp_path) -> Brain:
    return Brain(str(tmp_path / "brain"), mode="local")


def _add_edge(b: Brain, s: str, t: str, kind: str = "erweitert") -> None:
    b.add_edge(Edge(source=s, target=t, kind=kind, pending=False))


def test_merge_redirects_edges_and_removes_node(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    b.write_node(Node(id="t", text="Target"))
    _add_edge(b, "d", "t")  # deletee -> target
    r = merge_nodes(b, "s", "d", commit=False)
    nodes = {n.id for n in b.read_nodes()}
    assert "d" not in nodes and "s" in nodes and "t" in nodes
    edges = b.read_edges()
    # d->t wurde zu s->t umgeleitet
    assert any(e.source == "s" and e.target == "t" for e in edges)
    assert not any(e.source == "d" or e.target == "d" for e in edges)
    assert r.edges_redirected == 1


def test_merge_dedupes_shared_target(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    b.write_node(Node(id="t", text="Target"))
    _add_edge(b, "s", "t")
    _add_edge(b, "d", "t")
    r = merge_nodes(b, "s", "d", commit=False)
    edges = b.read_edges()
    assert sum(1 for e in edges if e.source == "s" and e.target == "t") == 1
    assert r.edges_removed >= 1


def test_merge_removes_self_loop(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    _add_edge(b, "s", "d")  # gegenseitige Kante -> Selbstschleife nach Merge
    r = merge_nodes(b, "s", "d", commit=False)
    edges = b.read_edges()
    assert not any(e.source == e.target for e in edges)
    assert r.edges_removed >= 1


def test_merge_combines_text(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor-Text"))
    b.write_node(Node(id="d", text="Deletee-Text"))
    merge_nodes(b, "s", "d", commit=False)
    s = next(n for n in b.read_nodes() if n.id == "s")
    assert "Survivor-Text" in s.text and "Deletee-Text" in s.text


def test_merge_drops_vector(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    b.write_node(Node(id="t", text="Target"))
    vec = b.path / "vectors.jsonl"
    vec.write_text(json.dumps({"id": "s", "vec": [1.0]}) + "\n"
                   + json.dumps({"id": "d", "vec": [2.0]}) + "\n"
                   + json.dumps({"id": "t", "vec": [3.0]}) + "\n", encoding="utf-8")
    merge_nodes(b, "s", "d", commit=False)
    ids = {json.loads(l)["id"] for l in vec.read_text().splitlines() if l.strip()}
    assert "d" not in ids and "s" in ids and "t" in ids


def test_merge_rebuilds_index(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    b.write_node(Node(id="d", text="Deletee"))
    merge_nodes(b, "s", "d", commit=False)
    index = (b.path / "INDEX.md").read_text(encoding="utf-8")
    assert "nodes/d.md" not in index and "nodes/s.md" in index


def test_merge_missing_node_raises(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    try:
        merge_nodes(b, "s", "missing", commit=False)
        assert False, "sollte ValueError werfen"
    except ValueError:
        pass


def test_merge_identical_raises(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="s", text="Survivor"))
    try:
        merge_nodes(b, "s", "s", commit=False)
        assert False, "sollte ValueError werfen"
    except ValueError:
        pass
