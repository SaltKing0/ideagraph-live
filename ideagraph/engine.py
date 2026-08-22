"""Ingest: Text rein → Node + Embedding + Edge-Vorschläge raus."""

from __future__ import annotations

from .model import Node
from .store import Store
from .embedder import get_embedder
from .suggester import suggest_edges


class Engine:
    """Der Wachstums-Loop als Klasse — Store + Embedder gebündelt."""

    def __init__(self, store: Store, embedder=None):
        self.store = store
        self.embedder = embedder if embedder is not None else get_embedder()

    def ingest(self, text: str) -> tuple[Node, list]:
        text = text.strip()
        if not text:
            raise ValueError("Leerer Text kann nicht ingestiert werden.")
        node = Node(text=text)
        vec = self.embedder.embed(text)
        self.store.add_node(node)
        candidates = {
            n.id: self.embedder.embed(n.text)
            for n in self.store.nodes if n.id != node.id
        }
        edges = suggest_edges(node.id, vec, candidates)
        for e in edges:
            self.store.add_edge(e)
        return node, edges


def main() -> None:
    import sys
    embedder_name = "hash" if "--hash" in sys.argv else "st"
    args = [a for a in sys.argv[1:] if a != "--hash"]
    if "-f" in args:
        path = args[args.index("-f") + 1]
        text = open(path, encoding="utf-8").read()
    elif "-" in args:
        text = sys.stdin.read()
    else:
        text = " ".join(args)
    if not text.strip():
        print("Nichts zu ingestieren. Nutzung: python -m ideagraph <text|->")
        sys.exit(1)
    store = Store()
    engine = Engine(store, get_embedder(embedder_name))
    node, edges = engine.ingest(text)
    print(f"Node {node.id}: {node.text}")
    for e in edges:
        print(f"  Vorschlag: --[{e.kind}]--> {e.target} (pending)")


if __name__ == "__main__":
    main()
