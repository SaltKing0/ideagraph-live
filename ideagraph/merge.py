"""Manuelle Near-Duplikat-Konsolidierung (`ig merge`).

Konsolidiert zwei eng verwandte Nodes zu einem: Alle Kanten des zu
entfernenden Nodes werden auf den Survivor umgeleitet (dedupliziert, ohne
Selbstschleifen), der Text wird zur Informationserhaltung angehängt, und der
entfernte Node wird als Tombstone markiert (nie hart gelöscht — der
Graph bleibt eine append-only Historie). INDEX.md wird neu gebaut und alles
in EINEM Commit geschrieben.

Audit #3/#9/#41-Fixes:
- Der Deletee wird getombstoned statt auf probation gesetzt und seine Datei
  wird nicht mehr vor dem Edge-Rewrite gelöscht (halb-geschriebener Zustand
  bei Crash mid-merge).
- Kanten mit Intent-Semantik (`supersedes`, `kontradiktorisch`, `continues`,
  `ersetzt`, …) werden NICHT blind umgeleitet: eine Deletee→X `supersedes`
  Kante sagt "der Deletee ersetzt X" — nach dem Merge ist der Survivor die
  Fortsetzung des Deletee-Inhalts, also wird die Kante zu
  Survivor→X umgeleitet NUR wenn die Richtung semantisch erhalten bleibt.
  Für supersedes/ersetzt/kontradiktorisch (Deletee als Quelle) wird die
  Kante stattdessen invalidiert (valid_to gesetzt) statt eine möglicherweise
  falsche Aussage über den Survivor zu machen; erweitert/ähnlich/verlinkt-
  Kanten sind richtungsneutral genug für einen Redirect.
- Merge-Provenance: der Merge-Commit und die Survivor-Node dokumentieren
  deletee-ID und Zeitpunkt; der Deletee-Status bleibt als Tombstone
  nachvollziehbar.

Dies ist die manuelle Ergänzung zur automatischen Ingest-Dedup (cos >= 0.92):
Near-Duplikate im Bereich ~0.78–0.92 bleiben unter der Auto-Schwelle und
brauchen diese Konsolidierung. Destruktiv — nur mit Bedacht, am besten nach
einem Dry-Run auf einer Brain-Kopie.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .brain import Brain

# Intent-Kanten mit gerichteter Semantik: ein Redirect Deletee→X auf
# Survivor→X würde die Aussage invertieren (Audit #9). Sie werden invalidiert
# statt umgeleitet. Richtungsneutrale Kinds (ähnlich/erweitert/same_as/…)
# werden normal umgeleitet.
DIRECTIONAL_KINDS = frozenset({
    "supersedes", "ersetzt", "kontradiktorisch", "replaces", "obsoletes",
    "korrigiert", "widerspricht",
})


@dataclass
class MergeResult:
    survivor: str
    deletee: str
    edges_redirected: int
    edges_removed: int  # Selbstschleifen + Duplikat-Paare
    edges_invalidated: int = 0  # gerichtete Intent-Kanten (nicht redirect-fähig)
    redirected_ids: list[str] = field(default_factory=list)
    invalidated_ids: list[str] = field(default_factory=list)


def _redirect_edges(edges: list, survivor: str, deletee: str,
                    now_iso: str) -> tuple[list, int, int, int, list[str], list[str]]:
    """Leitet Kanten des deletee auf den survivor um; entfernt Selbstschleifen + Duplikate.

    Gerichtete Intent-Kanten (DIRECTIONAL_KINDS) mit deletee als Quelle werden
    invalidiert (valid_to gesetzt) statt umgeleitet — der Survivor hat die
    Aussage "ersetzt X" nicht unbedingt geerbt (Audit #9).
    """
    new_edges: list = []
    seen: set[tuple] = set()
    removed = 0
    redirected = 0
    invalidated = 0
    redirected_ids: list[str] = []
    invalidated_ids: list[str] = []
    for e in edges:
        s, t = e.source, e.target
        if s == deletee or t == deletee:
            if e.kind in DIRECTIONAL_KINDS and s == deletee:
                # Aussage gilt über den Survivor nicht mehr — Kante historisieren.
                if e.valid_to is None:
                    e.valid_to = now_iso
                    invalidated += 1
                    invalidated_ids.append(e.id)
                else:
                    removed += 1
                new_edges.append(e)
                continue
            if s == deletee:
                s = survivor
                redirected += 1
            if t == deletee:
                t = survivor
                redirected += 1
            redirected_ids.append(e.id)
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
    return new_edges, removed, redirected, invalidated, redirected_ids, invalidated_ids


def _drop_vector(brain: Brain, deletee: str) -> None:
    vec_file: Path = brain.path / "vectors.jsonl"
    if not vec_file.exists():
        return
    lines = [l for l in vec_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    keep = [l for l in lines if json.loads(l).get("id") != deletee]
    brain.write_vectors({json.loads(l)["id"]: json.loads(l)["vec"] for l in keep})


def merge_nodes(
    brain: Brain,
    survivor_id: str,
    deletee_id: str,
    commit: bool = True,
    embedder=None,
) -> MergeResult:
    """Konsolidiert deletee in survivor. Destruktiv; ein Commit.

    embedder (optional): wenn gesetzt, wird der Survivor-Vektor nach dem
    Text-Append neu berechnet — ohne ihn bliebe der alte Vektor stehen und
    die Suche deduped/ranke gegen den VOR-Merge-Text (Audit-Befund
    "survivor vector stale"). Der CLI übergibt immer den Engine-Embedder.
    """
    if survivor_id == deletee_id:
        raise ValueError("Survivor und Deletee sind identisch.")
    # Git-Modus: Repo-Existenz + frischer Pull VOR der Mutation — sonst kann
    # der Merge auf einem stale Stand arbeiten und die History divergiert
    # (Audit-Befund "merge_nodes macht kein pull()").
    brain.ensure_ready()
    brain.pull()
    nodes = {n.id: n for n in brain.read_nodes()}
    if survivor_id not in nodes:
        raise ValueError(f"Node nicht gefunden: {survivor_id}")
    if deletee_id not in nodes:
        raise ValueError(f"Node nicht gefunden: {deletee_id}")
    survivor, deletee = nodes[survivor_id], nodes[deletee_id]
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Kanten umleiten + deduplizieren — VOR dem Löschen des Deletee-Files
    # (Audit #3: vorher wurde die Node-Datei zuerst unlinkt; ein Crash
    # zwischen unlink und Edge-Rewrite hinterließ einen halb-gemergten
    # Zustand mit dangling Edges auf eine nicht mehr existierende Node).
    edges = brain.read_edges(include_rejected=False)
    new_edges, removed, redirected, invalidated, redirected_ids, invalidated_ids = \
        _redirect_edges(edges, survivor_id, deletee_id, now_iso)
    # Keep unrelated dismissed suggestions available for undo. Decisions about
    # the deleted node cannot be restored after consolidation.
    rejected = [e for e in brain.read_edges(include_rejected=True)
                if e.rejected and deletee_id not in (e.source, e.target)]
    brain.write_edges(new_edges + rejected)

    # Text zusammenführen (Informationserhalt) — mit Merge-Provenance (Audit #41)
    survivor.text = (
        survivor.text.rstrip()
        + f"\n\n[konsolidiert aus {deletee_id} am {now_iso}: {deletee.text.strip()}]"
    )
    brain.write_node(survivor)

    # Deletee tombstonen (nie hart löschen — Audit #3: vorher unlink + Status
    # verloren, dangling Edges konnten auf eine "lebende" Probation-Node zeigen)
    brain.tombstone_node(deletee_id)

    # Vektor entfernen
    _drop_vector(brain, deletee_id)

    # Survivor-Vektor auffrischen: der Text ist gewachsen, der alte Vektor
    # repräsentiert den Vor-Merge-Text (Audit: "survivor vector stale").
    if embedder is not None:
        normalized = " ".join(survivor.text.lower().split())
        vecs = brain.read_vectors()
        vecs[survivor_id] = list(embedder.embed(normalized))
        brain.write_vectors(vecs)

    # INDEX neu bauen
    brain.rebuild_index()

    if commit:
        brain.commit_and_push(
            f"merge: {deletee_id} konsolidiert in {survivor_id} "
            f"({redirected} umgeleitet, {invalidated} invalidiert, {removed} entfernt)")

    return MergeResult(
        survivor=survivor_id,
        deletee=deletee_id,
        edges_redirected=redirected,
        edges_removed=removed,
        edges_invalidated=invalidated,
        redirected_ids=redirected_ids,
        invalidated_ids=invalidated_ids,
    )
