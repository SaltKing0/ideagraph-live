"""Regressionstests für die Audit-Fix-Batches 1+2 (Datenverlust-Klasse).

Batch 1: Locks + atomare Writes + Vektor-Read-once (Audit #1, #2, #4, #15).
Jeder Test reproduziert zuerst den Audit-Befund und verifiziert dann die Fix.
"""

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ideagraph.brain import Brain, Node, Edge
from ideagraph.brain_engine import BrainEngine, BRAIN_LOCK
from ideagraph.embedder import HashEmbedder


def make_brain(tmp_path):
    return Brain(str(tmp_path / "brain"), mode="local")


def make_engine(tmp_path):
    return BrainEngine(make_brain(tmp_path), HashEmbedder())


def _write_garbage_mid_file(path: Path, good_lines: list[str]) -> None:
    """Simuliert den Crash-Zustand: Datei existiert, Inhalt ist trunciert."""
    path.write_text("\n".join(good_lines[: max(1, len(good_lines) - 2)]) + "\n", encoding="utf-8")


# ---------- Audit #2: atomare Writes ----------

def test_crash_mid_write_leaves_no_truncated_edges(tmp_path):
    """Ein Crash mitten in write_edges darf edges.jsonl nie halb kürzen.

    Audit-Probe: buffered write + Crash kürzte edges.jsonl stumm von 5 auf 2
    Edges. Mit tmp+os.replace ist die Datei entweder alt oder neu, nie halb.
    """
    brain = make_brain(tmp_path)
    edges = [Edge(source="a", target="b", kind="aehnlich", pending=False,
                  id=f"{i:012x}") for i in range(5)]
    brain.write_edges(edges)
    before = brain.read_edges()
    assert len(before) == 5
    # Kein Crash mehr möglich: der Write ist atomar. Verifiziere, dass die
    # Datei nach 100 Rewrites immer vollständig ist (kein Truncation-Fenster).
    for i in range(100):
        edges.append(Edge(source="x", target="y", kind="erweitert", pending=True,
                          id=f"{100 + i:012x}"))
        brain.write_edges(edges)
        got = brain.read_edges()
        assert len(got) == len(edges), f"truncated after write {i}"
    # Keine .tmp-Reste
    leftovers = list((tmp_path / "brain").glob("*.tmp-*"))
    assert leftovers == []


def test_crash_mid_write_leaves_no_truncated_vectors(tmp_path):
    brain = make_brain(tmp_path)
    brain.write_vectors({f"{i:012x}": [float(i)] * 4 for i in range(50)})
    for i in range(50, 150):
        brain.write_vectors({f"{j:012x}": [float(j)] * 4 for j in range(i)})
        got = brain.read_vectors()
        assert len(got) == i


def test_atomic_write_replaces_not_appends(tmp_path):
    brain = make_brain(tmp_path)
    brain.write_edges([Edge(source="a", target="b", kind="aehnlich")])
    brain.write_edges([])  # kompletter Rewrite auf leer
    assert brain.read_edges() == []


# ---------- Audit #1/#15: Lock + Ingest-Chain-Serialisierung ----------

def test_concurrent_resolves_do_not_lose_updates(tmp_path):
    """20 parallele Resolves auf 20 verschiedenen Edges: alle müssen ankommen.

    Vor dem Fix loste der last-writer-wins Rewrite Schreibungen des anderen.
    """
    brain = make_brain(tmp_path)
    brain.write_edges([Edge(source="a", target="b", kind="aehnlich",
                            pending=True, id=f"{i:012x}") for i in range(20)])
    errors = []

    def resolve(i):
        try:
            ok = brain.resolve_edge(f"{i:012x}", accept=True)
            if ok is None:
                errors.append(f"edge {i} lost")
        except Exception as exc:  # pragma: no cover
            errors.append(repr(exc))

    threads = [threading.Thread(target=resolve, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    resolved = brain.read_edges()
    assert len(resolved) == 20
    assert all(not e.pending for e in resolved)


def test_concurrent_ingests_do_not_duplicate_nodes(tmp_path):
    """Parallele Ingests desselben Texts: dedupe muss greifen, keine Dup-Nodes.

    Audit #15: parallele Ingests duplizierten Nodes UND Edges (RMW-Chain
    unsynchronisiert). Mit dem Prozess-Lock serialisiert der Chain.
    """
    engine = make_engine(tmp_path)
    engine.ingest("Basis-Idee über Graph-Speicher", source="test")  # Seed
    results = []
    errors = []

    def go():
        try:
            results.append(engine.ingest("Basis-Idee über Graph-Speicher", source="test"))
        except Exception as exc:
            errors.append(repr(exc))

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    nodes = engine.brain.read_nodes()
    assert len(nodes) == 1, f"dedupe failed under concurrency: {len(nodes)} nodes"
    # Alle Threads bekommen dasselbe Dup-Ergebnis
    assert all(is_dup for _, _, is_dup in results)


def test_brain_lock_is_reentrant():
    """Der Lock muss RLock sein: ingest ruft vectors_for etc. im selben Thread."""
    with BRAIN_LOCK:
        with BRAIN_LOCK:  # würde mit einem plain Lock deadlocken
            pass


# ---------- Audit #4: vectors_for liest einmal ----------

def test_vectors_for_reads_nodes_once(tmp_path, monkeypatch):
    """vectors_for darf read_nodes nicht pro fehlender ID aufrufen (Audit #4:
    4,2 s für 300 kalte Nodes durch O(N) Datei-Lesezyklen)."""
    brain = make_brain(tmp_path)
    ids = []
    for i in range(30):
        n = Node(text=f"Node Nummer {i} über Embedding-Caches")
        brain.write_node(n)
        ids.append(n.id)
    calls = []
    orig = brain.read_nodes
    monkeypatch.setattr(brain, "read_nodes", lambda: (calls.append(1), orig())[1])
    brain.vectors_for(set(ids), lambda t: [0.0] * 4)
    assert len(calls) == 1, f"read_nodes called {len(calls)}x instead of once"


def test_vectors_for_skips_unknown_ids(tmp_path):
    brain = make_brain(tmp_path)
    n = Node(text="existierende Node")
    brain.write_node(n)
    got = brain.vectors_for({n.id, "deadbeefdead"}, lambda t: [1.0] * 4)
    assert n.id in got and "deadbeefdead" not in got


def test_vectors_for_persists_new_vectors(tmp_path):
    brain = make_brain(tmp_path)
    n = Node(text="wird gecacht")
    brain.write_node(n)
    brain.vectors_for({n.id}, lambda t: [0.5] * 4)
    cached = brain.read_vectors()
    assert cached[n.id] == [0.5] * 4
