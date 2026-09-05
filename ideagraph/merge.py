"""Manuelle Near-Duplikat-Konsolidierung (`ig merge`).

Konsolidiert zwei eng verwandte Nodes zu einem: Alle Kanten des zu
entfernenden Nodes werden auf den Survivor umgeleitet (dedupliziert, ohne
Selbstschleifen), der Text wird zur Informationserhaltung angehängt, und der
entfernte Node wird samt Vektor gelöscht. INDEX.md wird neu gebaut und alles
in EINEM Commit geschrieben.

Dies ist die manuelle Ergänzung zur automatischen Ingest-Dedup (cos >= 0.92):
Near-Duplikate im Bereich ~0.78–0.92 bleiben unter der Auto-Schwelle und
brauchen diese Konsolidierung. Destruktiv — nur mit Bedacht, am besten nach
einem Dry-Run auf einer Brain-Kopie.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .brain import Brain


@dataclass
class MergeResult:
    survivor: str
    deletee: str
    edges_redirected: int
    edges_removed: int  # Selbstschleifen + Duplikat-Paare


def _redirect_edges(edges: list, survivor: str, deletee: str) -> tuple[list, int, int]:
    """Leitet Kanten des deletee auf den survivor um; entfernt Selbstschleifen + Duplikate."""
    new_edges: list = []
    seen: set[tuple] = set()
    removed = 0
    redirected = 0
    for e in edges:
        s, t = e.source, e.target
        if s == deletee:
            s = survivor
            redirected += 1
        if t == deletee:
            t = survivor
            redirected += 1
        if s == t:  # Selbstschleife nach Merge
            removed += 1
            continue
        key = tuple(sorted((s, t)))
        if key in seen:  # Duplikat-Paar (Survivor hatte das Ziel schon)
            removed += 1
            continue
        seen.add(key)
        e.source, e.target = s, t
        new_edges.append(e)
    return new_edges, removed, redirected


def _drop_vector(brain: Brain, deletee: str) -> None:
    vec_file: Path = brain.path / "vectors.jsonl"
    if not vec_file.exists():
        return
    lines = [l for l in vec_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    keep = [l for l in lines if json.loads(l).get("id") != deletee]
    vec_file.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")


def merge_nodes(
    brain: Brain,
    survivor_id: str,
    deletee_id: str,
    commit: bool = True,
) -> MergeResult:
    """Konsolidiert deletee in survivor. Destruktiv; ein Commit."""
    if survivor_id == deletee_id:
        raise ValueError("Survivor und Deletee sind identisch.")
    nodes = {n.id: n for n in brain.read_nodes()}
    if survivor_id not in nodes:
        raise ValueError(f"Node nicht gefunden: {survivor_id}")
    if deletee_id not in nodes:
        raise ValueError(f"Node nicht gefunden: {deletee_id}")
    survivor, deletee = nodes[survivor_id], nodes[deletee_id]

    # Text zusammenführen (Informationserhalt)
    survivor.text = (
        survivor.text.rstrip()
        + f"\n\n[konsolidiert aus {deletee_id}: {deletee.text.strip()}]"
    )
    brain.write_node(survivor)

    # Deletee-Datei entfernen
    dp = brain.node_path(deletee_id)
    if dp.exists():
        dp.unlink()

    # Kanten umleiten + deduplizieren
    edges = brain.read_edges()
    new_edges, removed, redirected = _redirect_edges(edges, survivor_id, deletee_id)
    brain.write_edges(new_edges)

    # Vektor entfernen
    _drop_vector(brain, deletee_id)

    # INDEX neu bauen
    brain.rebuild_index()

    if commit:
        brain.commit_and_push(f"merge: {deletee_id} konsolidiert in {survivor_id}")

    return MergeResult(
        survivor=survivor_id,
        deletee=deletee_id,
        edges_redirected=redirected,
        edges_removed=removed,
    )
