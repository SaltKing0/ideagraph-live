"""Hygiene-/Status-Analyse (`ig status`, `ig near-dup`).

Read-only Berichte, die die Pflege des Brains unterstützen:

- `near_dup_pairs` — findet Near-Duplikat-Paare im Kosinus-Band unterhalb der
  Auto-Dedup-Schwelle (0.92). Diese Paare brauchen eine manuelle
  `ig merge`-Entscheidung (siehe `ideagraph.merge`).
- `connectivity` / `status_counts` — Inseln, schwache Nodes, Orphans und
  Status-Verteilung, damit Unterbesetzung und Hygiene-Backlog sichtbar werden.

Alles read-only — es wird nichts am Brain verändert.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .brain import Brain

# Auto-Dedup-Schwelle in brain_engine (cos >= 0.92 -> merge). Paare darunter,
# aber nah genug, sind Kandidaten für die manuelle Konsolidierung.
DEFAULT_DEDUP_THRESHOLD = 0.92
DEFAULT_NEAR_LO = 0.78


@dataclass
class NearDup:
    score: float
    a: str
    b: str
    a_text: str
    b_text: str


def _load_vectors(brain: Brain) -> tuple[list[str], np.ndarray]:
    """Liest vectors.jsonl; nutzt die dominante Dimension (384 real vs 64 Hash)."""
    vec_file = brain.path / "vectors.jsonl"
    if not vec_file.exists():
        return [], np.zeros((0, 0), dtype=np.float32)
    vecs: dict[str, list[float]] = {}
    lens: Counter = Counter()
    for l in vec_file.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        o = json.loads(l)
        vecs[o["id"]] = o["vec"]
        lens[len(o["vec"])] += 1
    if not vecs:
        return [], np.zeros((0, 0), dtype=np.float32)
    dom = max(lens, key=lambda k: lens[k])
    ids = [n for n, v in vecs.items() if len(v) == dom]
    V = np.array([vecs[n] for n in ids], dtype=np.float32)
    V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
    return ids, V


def near_dup_pairs(
    brain: Brain,
    lo: float = DEFAULT_NEAR_LO,
    hi: float = DEFAULT_DEDUP_THRESHOLD,
    max_pairs: int | None = None,
) -> list[NearDup]:
    """Findet Near-Duplikat-Paare im Kosinus-Band [lo, hi), absteigend nach Score."""
    ids, V = _load_vectors(brain)
    if len(ids) < 2:
        return []
    S = V @ V.T
    np.fill_diagonal(S, -1.0)
    texts = {n.id: n.text for n in brain.read_nodes()}
    pairs: list[NearDup] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            c = float(S[i][j])
            if lo <= c < hi:
                a, b = ids[i], ids[j]
                pairs.append(NearDup(c, a, b, texts.get(a, a)[:72], texts.get(b, b)[:72]))
    pairs.sort(key=lambda p: p.score, reverse=True)
    if max_pairs:
        pairs = pairs[:max_pairs]
    return pairs


@dataclass
class Connectivity:
    total: int
    edges: int
    islands: list[str]   # degree <= 1
    weak: list[str]      # degree == 2
    orphans: list[str]   # degree == 0
    max_degree: int
    mean_degree: float


def connectivity(brain: Brain) -> Connectivity:
    nodes = brain.read_nodes()
    edges = brain.read_edges()
    deg: Counter = Counter()
    for e in edges:
        deg[e.source] += 1
        deg[e.target] += 1
    ids = [n.id for n in nodes]
    islands = [n for n in ids if deg[n] <= 1]
    weak = [n for n in ids if deg[n] == 2]
    orphans = [n for n in ids if deg[n] == 0]
    vals = [deg[n] for n in ids] or [0]
    return Connectivity(
        total=len(ids),
        edges=len(edges),
        islands=islands,
        weak=weak,
        orphans=orphans,
        max_degree=max(vals),
        mean_degree=sum(vals) / len(vals),
    )


def status_counts(brain: Brain) -> Counter:
    c: Counter = Counter()
    for n in brain.read_nodes():
        c[n.status] += 1
    return c


def render_status(brain: Brain) -> str:
    c = connectivity(brain)
    st = status_counts(brain)
    lines = [
        f"Status ({c.total} Nodes / {c.edges} Edges):",
        f"  Grad: max={c.max_degree} mean={c.mean_degree:.1f}",
        f"  Orphans (0 Kanten): {len(c.orphans)}",
        f"  Inseln (<=1 Kante): {len(c.islands)}",
        f"  Schwach (==2 Kanten): {len(c.weak)}",
        f"  Status: {dict(st)}",
    ]
    if c.islands:
        lines.append("  Insel-Nodes: " + ", ".join(c.islands[:15]) + (" …" if len(c.islands) > 15 else ""))
    if c.orphans:
        lines.append("  Orphan-Nodes: " + ", ".join(c.orphans[:15]) + (" …" if len(c.orphans) > 15 else ""))
    return "\n".join(lines)


def render_near_dup(pairs: list[NearDup]) -> str:
    if not pairs:
        return "Keine Near-Duplikate im Band."
    lines = [f"{len(pairs)} Near-Duplikat-Paare (Konsolidierung via `ig merge` prüfen):"]
    for p in pairs:
        lines.append(f"[{p.score:.3f}] {p.a} ↔ {p.b}")
        lines.append(f"    {p.a_text}")
        lines.append(f"    {p.b_text}")
    return "\n".join(lines)
