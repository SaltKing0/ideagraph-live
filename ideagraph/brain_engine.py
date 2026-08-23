"""Wachstums-Loop auf Brain-Basis: ingest → embed → suggest → commit.

Jeder Ingest ist ein Git-Commit im privaten Repo — der Graph wächst
als sichtbare Commit-Historie.
"""

from __future__ import annotations

from .brain import Brain, Node, Edge
from .embedder import get_embedder
from .suggester import suggest


class BrainEngine:
    def __init__(self, brain: Brain, embedder=None):
        self.brain = brain
        self.embedder = embedder if embedder is not None else get_embedder()

    def ingest(self, text: str, source: str = "human", tags: list[str] | None = None) -> tuple[Node, list[Edge]]:
        text = text.strip()
        if not text:
            raise ValueError("Leerer Text kann nicht ingestiert werden.")
        self.brain.pull()
        node = Node(text=text, source=source, tags=tags)
        self.brain.write_node(node)
        vec = self.embedder.embed(text)
        candidates = {n.id: self.embedder.embed(n.text)
                      for n in self.brain.read_nodes() if n.id != node.id}
        edges = [Edge(source=s.source, target=s.target, kind=s.kind, pending=True)
                 for s in suggest(node.id, vec, candidates)]
        for e in edges:
            self.brain.add_edge(e)
        self.brain.rebuild_index()
        self.brain.commit_and_push(
            f"ingest: {text[:50]}{'…' if len(text) > 50 else ''} (+{len(edges)} Vorschläge)")
        return node, edges

    def resolve(self, edge_id: str, accept: bool) -> Edge | None:
        self.brain.pull()
        edge = self.brain.resolve_edge(edge_id, accept)
        if edge is not None:
            action = "accept" if accept else "reject"
            self.brain.commit_and_push(f"edge {action}: {edge_id[:8]} [{edge.kind}]")
        return edge
