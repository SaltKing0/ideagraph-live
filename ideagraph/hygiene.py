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
    """Liest vectors.jsonl; nutzt die dominante Dimension (384 real vs 64 Hash).

    Audit #38: float32 rundet Band-Grenzfälle falsch (0.9199999990 float64 →
    0.9200000167 float32 — das Paar fällt durch BEIDE Mechanismen: kein Dup
    im Engine, aber auch nicht im Review-Band). Deshalb float64."""
    vec_file = brain.path / "vectors.jsonl"
    if not vec_file.exists():
        return [], np.zeros((0, 0), dtype=np.float64)
    vecs: dict[str, list[float]] = {}
    lens: Counter = Counter()
    for l in vec_file.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        try:
            o = json.loads(l)
        except json.JSONDecodeError:
            continue  # Audit #17-Familie: korrupte Zeile killt nicht den Report
        vecs[o["id"]] = o["vec"]
        lens[len(o["vec"])] += 1
    if not vecs:
        return [], np.zeros((0, 0), dtype=np.float64)
    dom = max(lens, key=lambda k: lens[k])
    ids = [n for n, v in vecs.items() if len(v) == dom]
    V = np.array([vecs[n] for n in ids], dtype=np.float64)
    V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-12)
    return ids, V


def near_dup_pairs(
    brain: Brain,
    lo: float = DEFAULT_NEAR_LO,
    hi: float = DEFAULT_DEDUP_THRESHOLD,
    max_pairs: int | None = None,
) -> list[NearDup]:
    """Findet Near-Duplikat-Paare im Kosinus-Band [lo, hi), absteigend nach Score.

    Audit #38: das obere Band-Ende ist inklusiv-versus-Engine konsistent — ein
    float64-cos 0.9199999990 ist im Engine KEIN Dup (0.92-Schwelle), muss also
    im Review-Band erscheinen. Ein epsilon-Puffer an `hi` verhindert, dass
    Rundung solche Paare aus beiden Mechanismen fallen lässt.
    Audit #39: die Paar-Iteration läuft vektorisiert (triu-Maske) statt in
    O(N²)-Python-Schleifen (4M Iterationen @2k, ~50 s @20k)."""
    ids, V = _load_vectors(brain)
    if len(ids) < 2:
        return []
    S = V @ V.T
    np.fill_diagonal(S, -1.0)
    band = (S >= lo) & (S < hi + 1e-6)
    band = np.triu(band, k=1)
    ii, jj = np.nonzero(band)
    texts = {n.id: n.text for n in brain.read_nodes()}
    pairs = [NearDup(float(S[i][j]), ids[int(i)], ids[int(j)],
                     texts.get(ids[int(i)], ids[int(i)])[:72],
                     texts.get(ids[int(j)], ids[int(j)])[:72])
             for i, j in zip(ii, jj)]
    pairs.sort(key=lambda p: p.score, reverse=True)
    if max_pairs is not None:
        # Audit #60: `if max_pairs:` behandelte max_pairs=0 als "unbegrenzt" —
        # 0 heißt Limit 0 (keine Paare).
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
    # Audit #40: invalidierte Edges (valid_to gesetzt) zählen nicht mehr zur
    # Konnektivität — sonst widerspricht der Status-Report der Admit-Rule-Logik
    # (_has_relation ignoriert sie korrekt).
    live_edges = [e for e in edges if e.valid_to is None]
    deg: Counter = Counter()
    for e in live_edges:
        deg[e.source] += 1
        deg[e.target] += 1
    ids = [n.id for n in nodes]
    islands = [n for n in ids if deg[n] <= 1]
    weak = [n for n in ids if deg[n] == 2]
    orphans = [n for n in ids if deg[n] == 0]
    vals = [deg[n] for n in ids] or [0]
    return Connectivity(
        total=len(ids),
        edges=len(live_edges),
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
