"""CLI für das Brain: init, ingest, pending, accept, reject, link, search.

Beispiele:
  python -m ideagraph init [--remote <brain-repo-url>]
  python -m ideagraph ingest "Neue Idee ..." [--source agent/bot] [--allow-dup]
  cat notiz.md | python -m ideagraph ingest -
  python -m ideagraph pending
  python -m ideagraph accept <edge_id>
  python -m ideagraph reject <edge_id>
  python -m ideagraph link <node_a> <node_b> [--kind same_as]
  python -m ideagraph search "attention"

Env wie beim Server: IG_BRAIN_PATH, IG_BRAIN_REMOTE, IG_BRAIN_MODE,
IDEAGRAPH_EMBEDDER (st|hash).
"""

from __future__ import annotations

import os
import sys

from .brain import Brain
from .brain_engine import BrainEngine
from .embedder import get_embedder
from .retrieval import retrieve


def make_engine() -> BrainEngine:
    brain = Brain(
        path=os.environ.get("IG_BRAIN_PATH", os.path.expanduser("~/ideagraph-brain")),
        # Kein privater/persönlicher Default-Remote mehr: nur für `git clone`
        # beim ersten Einrichten nötig. Bestehende Clones nutzen ihr eigenes
        # origin-Repo (pull/push funktionieren ohne Remote-Angabe).
        remote=os.environ.get("IG_BRAIN_REMOTE", "") or None,
        mode=os.environ.get("IG_BRAIN_MODE", "git"),
    )
    return BrainEngine(brain, get_embedder(os.environ.get("IDEAGRAPH_EMBEDDER", "st")))


def _short(text: str, n: int = 70) -> str:
    text = text.replace("\n", " ")
    return text[: n - 1] + "…" if len(text) > n else text


def cmd_ingest(engine: BrainEngine, args: list[str]) -> None:
    source = "human"
    allow_dup = False
    rest: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--source":
            source = args[i + 1]
            i += 2
        elif args[i] == "--allow-dup":
            allow_dup = True
            i += 1
        else:
            rest.append(args[i])
            i += 1
    if rest == ["-"]:
        text = sys.stdin.read()
    else:
        text = " ".join(rest)
    if not text.strip():
        print("Nichts zu ingestieren. Nutzung: ig ingest \"Text\" | ig ingest - < datei")
        sys.exit(1)
    node, edges, dup = engine.ingest(text, source=source, allow_duplicates=allow_dup)
    if dup:
        print(f"Duplikat → gemergt in {node.id}: {_short(node.text)}")
    else:
        print(f"Node {node.id}: {_short(node.text)}")
        for e in edges:
            print(f"  Vorschlag: --[{e.kind}]--> {e.target} ({e.id})")


def cmd_pending(engine: BrainEngine, args: list[str]) -> None:
    edges = [e for e in engine.brain.read_edges() if e.pending]
    texts = {n.id: n.text for n in engine.brain.read_nodes()}
    if not edges:
        print("Keine offenen Vorschläge.")
        return
    for e in edges:
        print(f"{e.id}  [{e.kind}]  {_short(texts.get(e.source, e.source), 40)}"
              f"  ↔  {_short(texts.get(e.target, e.target), 40)}")
    print(f"\n{len(edges)} pending · akzeptieren: ig accept {edges[0].id}")


def _resolve_cmd(engine: BrainEngine, edge_id: str, accept: bool) -> None:
    edge = engine.resolve(edge_id, accept)
    if edge is None:
        print(f"Edge {edge_id} nicht gefunden oder nicht pending.")
        sys.exit(1)
    print(f"{'akzeptiert' if accept else 'verworfen'}: {edge_id} [{edge.kind}]")


def cmd_link(engine: BrainEngine, args: list[str]) -> None:
    kind = "same_as"
    if "--kind" in args:
        i = args.index("--kind")
        kind = args[i + 1]
        args = args[:i] + args[i + 2:]
    if len(args) != 2:
        print("Nutzung: ig link <node_a> <node_b> [--kind same_as]")
        sys.exit(1)
    try:
        edge = engine.link(args[0], args[1], kind)
    except ValueError as exc:
        print(f"Fehler: {exc}")
        sys.exit(1)
    print(f"verlinkt: {edge.source} --[{edge.kind}]--> {edge.target}")


def cmd_init(engine: BrainEngine, args: list[str]) -> None:
    remote = None
    if "--remote" in args:
        i = args.index("--remote")
        remote = args[i + 1] if i + 1 < len(args) else None
    brain = engine.brain
    brain.init(remote=remote, commit=True)
    print(f"✓ Brain-Repo initialisiert: {brain.path}")
    print(f"  Modus: {brain.mode}" + (f" · Remote: {remote}" if remote else " (lokal, ohne Remote)"))
    print("  Struktur: nodes/ · edges.jsonl · vectors.jsonl · INDEX.md")
    print("Jetzt loslegen:")
    print("  ig ingest \"Erste Idee ...\"            # CLI-Ingest")
    print("  uvicorn ideagraph.server:app --port 8000   # → http://localhost:8000")


def cmd_search(engine: BrainEngine, args: list[str]) -> None:
    if not args:
        print("Nutzung: ig search <begriff>")
        sys.exit(1)
    q = " ".join(args)
    id2node = {n.id: n for n in engine.brain.read_nodes()}
    hits = retrieve(engine, q, k=5)
    for nid, score in hits:
        n = id2node.get(nid)
        if n is not None:
            print(f"{nid}  {score:.3f}  {_short(n.text)}")
    print(f"\n{len(hits)} Treffer (hybrid dense+BM25)")


COMMANDS = {
    "init": cmd_init,
    "ingest": cmd_ingest,
    "pending": lambda e, a: cmd_pending(e, a),
    "accept": lambda e, a: _resolve_cmd(e, a[0], True),
    "reject": lambda e, a: _resolve_cmd(e, a[0], False),
    "link": cmd_link,
    "search": cmd_search,
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    cmd, rest = args[0], args[1:]
    fn = COMMANDS.get(cmd)
    if fn is None:
        print(f"Unbekannter Befehl: {cmd}. Verfügbar: {', '.join(COMMANDS)}")
        sys.exit(1)
    fn(make_engine(), rest)


if __name__ == "__main__":
    main()
