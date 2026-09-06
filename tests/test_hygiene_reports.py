"""Tests für die Hygiene-/Status-Reports (`ig status`, `ig near-dup`).

Definieren das erwartete Verhalten von near_dup_pairs / connectivity /
status_counts, bevor die CLI darauf aufbaut (measure-first).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ideagraph.brain import Brain, Node, Edge
from ideagraph.hygiene import (
    near_dup_pairs,
    connectivity,
    status_counts,
    DEFAULT_DEDUP_THRESHOLD,
)


def _brain(tmp_path) -> Brain:
    return Brain(str(tmp_path / "brain"), mode="local")


def _write_vecs(brain: Brain, vecs: dict[str, list[float]]) -> None:
    (brain.path / "vectors.jsonl").write_text(
        "".join(json.dumps({"id": k, "vec": v}) + "\n" for k, v in vecs.items()),
        encoding="utf-8",
    )


def test_near_dup_finds_band_pair(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    b.write_node(Node(id="b", text="Thema A Variante"))
    b.write_node(Node(id="c", text="Ganz anderes Thema"))
    # a=[1,0,0], b=[0.8,0.6,0] -> cos=0.8 (im Band), c=[0,1,0] -> cos(a,c)=0
    _write_vecs(b, {"a": [1, 0, 0], "b": [0.8, 0.6, 0], "c": [0, 1, 0]})
    pairs = near_dup_pairs(b, lo=0.78, hi=0.92)
    assert len(pairs) == 1
    p = pairs[0]
    assert {p.a, p.b} == {"a", "b"}
    assert 0.78 <= p.score < 0.92


def test_near_dup_band_excludes_outside(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="A"))
    b.write_node(Node(id="x", text="X"))
    b.write_node(Node(id="y", text="Y"))
    # x=[1,0,0] (cos 1.0 mit a -> >=hi, ausgeschlossen), y=[0.6,0.8,0] (cos 0.6 -> <lo)
    _write_vecs(b, {"a": [1, 0, 0], "x": [1, 0, 0], "y": [0.6, 0.8, 0]})
    pairs = near_dup_pairs(b, lo=0.78, hi=0.92)
    assert pairs == []  # 1.0 >= hi und 0.6 < lo, beide raus


def test_near_dup_sorted_desc(tmp_path):
    b = _brain(tmp_path)
    for nid in ["a", "b", "c", "d"]:
        b.write_node(Node(id=nid, text=nid))
    # a-b=0.9, a-c=0.8, a-d=0.0 (Einheitsvektoren)
    _write_vecs(b, {
        "a": [1, 0, 0],
        "b": [0.9, 0.4359, 0],
        "c": [0.8, 0.6, 0],
        "d": [0, 1, 0],
    })
    pairs = near_dup_pairs(b, lo=0.78, hi=0.92)
    assert len(pairs) == 2
    assert pairs[0].score > pairs[1].score


def test_connectivity_detects_islands_and_orphans(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="island", text="Insel"))
    b.write_node(Node(id="orphan", text="Orphan"))
    b.write_node(Node(id="weak", text="Schwach"))
    b.write_node(Node(id="hub", text="Hub"))
    # hub-weak, hub-weak2 -> weak hat 2 Kanten; island 1; orphan 0
    b.add_edge(Edge(source="hub", target="weak", kind="erweitert", pending=False))
    b.add_edge(Edge(source="hub", target="island", kind="erweitert", pending=False))
    b.add_edge(Edge(source="weak", target="hub", kind="erweitert", pending=False))
    c = connectivity(b)
    assert c.total == 4
    assert "orphan" in c.orphans
    assert "island" in c.islands  # degree 1
    assert "weak" not in c.islands  # degree 2 (weak, nicht Insel)


def test_status_counts(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="A", status="probation"))
    b.write_node(Node(id="b", text="B", status="active"))
    b.write_node(Node(id="c", text="C", status="tombstone"))
    c = status_counts(b)
    assert c["probation"] == 1 and c["active"] == 1 and c["tombstone"] == 1


def test_default_threshold_constant():
    assert DEFAULT_DEDUP_THRESHOLD == 0.92
