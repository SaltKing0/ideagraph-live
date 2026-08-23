"""Wachstums-Loop auf Brain-Basis: ingest → embed → suggest → commit.

Jeder Ingest ist ein Git-Commit im privaten Repo — der Graph wächst
als sichtbare Commit-Historie.
"""

from __future__ import annotations

from .brain import Brain, Node, Edge
from .embedder import get_embedder
from .similarity import cosine
from .suggester import suggest

DEDUPE_THRESHOLD = 0.92


def _normalize(text: str) -> str:
    """Für den Duplikats-Vergleich: Kleinbuchstaben, Whitespace eingeebnet."""
    return " ".join(text.lower().split())


class BrainEngine:
    def __init__(self, brain: Brain, embedder=None, dedupe_threshold: float = DEDUPE_THRESHOLD):
        self.brain = brain
        self.embedder = embedder if embedder is not None else get_embedder()
        self.dedupe_threshold = dedupe_threshold

    def _find_duplicate(self, vec: list[float], exclude_id: str | None = None) -> Node | None:
        """Nächster Node über dem Dedupe-Threshold — oder None. Nutzt den Vektor-Cache."""
        node_ids = {n.id for n in self.brain.read_nodes() if n.id != exclude_id}
        vectors = self.brain.vectors_for(node_ids, lambda t: self.embedder.embed(_normalize(t)))
        best: tuple[float, str] | None = None
        for nid, v in vectors.items():
            sim = cosine(vec, v)
            if sim >= self.dedupe_threshold and (best is None or sim > best[0]):
                best = (sim, nid)
        if best is None:
            return None
        return next((n for n in self.brain.read_nodes() if n.id == best[1]), None)

    def ingest(self, text: str, source: str = "human", tags: list[str] | None = None,
               allow_duplicates: bool = False) -> tuple[Node, list[Edge], bool]:
        """Ingest mit Dedupe. Rückgabe: (node, edges, is_duplicate).

        Bei Near-Duplicate (cosine >= threshold gegen normalisierten Text)
        wird kein neuer Node angelegt, sondern der bestehende gemergt:
        Quelle wird an der Node protokolliert, Commit-Meldung sagt "dup".
        """
        text = text.strip()
        if not text:
            raise ValueError("Leerer Text kann nicht ingestiert werden.")
        self.brain.pull()
        vec = self.embedder.embed(_normalize(text))
        if not allow_duplicates:
            dup = self._find_duplicate(vec)
            if dup is not None:
                self.brain.merge_node(dup, source=source)
                self.brain.rebuild_index()
                self.brain.commit_and_push(
                    f"ingest dup of {dup.id[:8]}: {_normalize(text)[:50]}…")
                return dup, [], True
        node = Node(text=text, source=source, tags=tags)
        self.brain.write_node(node)
        # Embedding-Cache: nur neue Nodes werden embeddet, Rest kommt aus vectors.jsonl
        others = {n.id for n in self.brain.read_nodes() if n.id != node.id}
        candidates = self.brain.vectors_for(others, lambda t: self.embedder.embed(_normalize(t)))
        edges = [Edge(source=s.source, target=s.target, kind=s.kind, pending=True)
                 for s in suggest(node.id, vec, candidates)]
        existing_pairs = {(e.source, e.target) for e in self.brain.read_edges()}
        new_edges = [e for e in edges if (e.source, e.target) not in existing_pairs]
        for e in new_edges:
            self.brain.add_edge(e)
        # Vektor der neuen Node cachen
        cached = self.brain.read_vectors()
        cached[node.id] = vec
        self.brain.write_vectors(cached)
        self.brain.rebuild_index()
        self.brain.commit_and_push(
            f"ingest: {text[:50]}{'…' if len(text) > 50 else ''} (+{len(new_edges)} Vorschläge)")
        return node, new_edges, False

    def resolve(self, edge_id: str, accept: bool) -> Edge | None:
        self.brain.pull()
        edge = self.brain.resolve_edge(edge_id, accept)
        if edge is not None:
            action = "accept" if accept else "reject"
            self.brain.commit_and_push(f"edge {action}: {edge_id[:8]} [{edge.kind}]")
        return edge
