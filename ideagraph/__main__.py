"""CLI for the brain: init, ingest, pending, accept, reject, link, search.

Beispiele:
  python -m ideagraph init [--remote <brain-repo-url>]
  python -m ideagraph ingest "Neue Idee ..." [--source agent/bot] [--allow-dup]
  cat notiz.md | python -m ideagraph ingest -
  python -m ideagraph pending
  python -m ideagraph accept <edge_id>
  python -m ideagraph reject <edge_id>
  python -m ideagraph link <node_a> <node_b> [--kind same_as]
  python -m ideagraph search "attention"
  python -m ideagraph gaps [--taxonomy tax.json] [--min 10] [--json]
  python -m ideagraph merge <survivor_id> <deletee_id>   # Near-Dup konsolidieren
  python -m ideagraph near-dup [--lo 0.78] [--hi 0.92]   # Near-Dup-Paare melden
  python -m ideagraph status [--json]                     # connectivity/hygiene report

Env wie beim Server: IG_BRAIN_PATH, IG_BRAIN_REMOTE, IG_BRAIN_MODE,
IDEAGRAPH_EMBEDDER (st|hash).
"""

from __future__ import annotations

import os
import sys

from .brain import Brain
from .brain_engine import BrainEngine
from .embedder import get_embedder
from .gaps import analyze_coverage, find_gaps, render, load_taxonomy
from .hygiene import near_dup_pairs, connectivity, status_counts, render_near_dup, render_status
from .merge import merge_nodes
from .retrieval import retrieve


def make_engine() -> BrainEngine:
    # Audit #33: expanduser muss AUCH auf einen explizit gesetzten Env-Wert
    # actually applied (IG_BRAIN_PATH=~/x used to create a literal ./~).
    brain_path = os.path.expanduser(
        os.environ.get("IG_BRAIN_PATH", os.path.expanduser("~/ideagraph-brain")))
    brain = Brain(
        path=brain_path,
        # No private/personal default remote: only needed for `git clone`
        # on first setup. Existing clones use their own
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
            # Audit #26: fehlender Wert nach --source ist ein Usage-Fehler,
            # kein IndexError-Traceback.
            if i + 1 >= len(args):
                print("Nutzung: ig ingest \"Text\" --source <quelle>")
                sys.exit(1)
            source = args[i + 1]
            i += 2
        elif args[i] == "--allow-dup":
            allow_dup = True
            i += 1
        else:
            rest.append(args[i])
            i += 1
    # Audit #32: '-' ist der stdin-Marker — auch in gemischten Args. Vorher
    # 'ig ingest - extra' used to ingest the literal text "- extra"
    # (exit 0, node created). A '-' token means stdin; an extra
    # Text daneben ist ein Fehler.
    if "-" in rest:
        if len(rest) > 1:
            print("Nutzung: '-' (stdin) kann nicht mit Text-Argumenten kombiniert werden.")
            sys.exit(1)
        text = sys.stdin.read()
    else:
        text = " ".join(rest)
    if not text.strip():
        print("Nichts zu ingestieren. Nutzung: ig ingest \"Text\" | ig ingest - < datei")
        sys.exit(1)
    node, edges, dup = engine.ingest(text, source=source, allow_duplicates=allow_dup)
    if dup:
        print(f"Duplicate → merged into {node.id}: {_short(node.text)}")
    else:
        print(f"Node {node.id}: {_short(node.text)}")
        for e in edges:
            print(f"  Suggestion: --[{e.kind}]--> {e.target} ({e.id})")


def cmd_pending(engine: BrainEngine, args: list[str]) -> None:
    edges = [e for e in engine.brain.read_edges() if e.pending]
    texts = {n.id: n.text for n in engine.brain.read_nodes()}
    if not edges:
        print("No pending suggestions.")
        return
    for e in edges:
        print(f"{e.id}  [{e.kind}]  {_short(texts.get(e.source, e.source), 40)}"
              f"  ↔  {_short(texts.get(e.target, e.target), 40)}")
    print(f"\n{len(edges)} pending · akzeptieren: ig accept {edges[0].id}")


def _first_or_usage(args: list[str], cmd: str) -> str:
    """Audit #26: fehlendes Positionsargument → Usage-Zeile statt IndexError."""
    if not args:
        print(f"Nutzung: ig {cmd} <edge_id>")
        sys.exit(1)
    return args[0]


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
        # Audit #26: fehlender Wert nach --kind → Usage-Fehler statt IndexError.
        if i + 1 >= len(args):
            print("Nutzung: ig link <node_a> <node_b> [--kind same_as]")
            sys.exit(1)
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
    demo = "--demo" in args
    if "--remote" in args:
        i = args.index("--remote")
        remote = args[i + 1] if i + 1 < len(args) else None
    brain = engine.brain
    if demo:
        from .demo import build_demo_brain
        try:
            stats = build_demo_brain(str(brain.path))
        except FileExistsError:
            # Audit #58: freundliche Meldung statt roher Traceback — ein
            # a non-empty directory is never overwritten.
            print(f"Fehler: {brain.path} existiert bereits und ist nicht leer.")
            print("Das Demo-Brain wird nie in ein bestehendes Verzeichnis geschrieben.")
            print("Choose a different path: IG_BRAIN_PATH=<path> ig init --demo")
            sys.exit(1)
        print(f"✓ Demo-Brain initialisiert: {brain.path}")
        print(f"  {stats['nodes']} Nodes · {stats['edges']} Edges "
              f"({stats['pending']} pending for HITL review)")
        print("  Enthalten: alle Edge-Typen, 1 Orphan-Insel (demos `ig status`),")
        print("  1 Near-Dup-Paar (demos `ig near-dup` + `ig merge`), 1 same_as-Paar.")
        print("Jetzt ausprobieren:")
        print("  ig status                     # Insel + Hygiene-Report sehen")
        print("  ig near-dup                   # das Demo-Near-Dup-Paar finden")
        print("  ig pending                    # review the 2 pending suggestions")
        print("  ig search \"RAG\"               # hybride Suche (sofort funktional)")
        print("  uvicorn ideagraph.server:app --port 8000   # → http://localhost:8000")
        return
    brain.init(remote=remote, commit=True)
    print(f"✓ Brain-Repo initialisiert: {brain.path}")
    print(f"  Modus: {brain.mode}" + (f" · Remote: {remote}" if remote else " (lokal, ohne Remote)"))
    print("  Struktur: nodes/ · edges.jsonl · vectors.jsonl · INDEX.md")
    print("Jetzt loslegen:")
    print("  ig ingest \"Erste Idee ...\"            # CLI-Ingest")
    print("  uvicorn ideagraph.server:app --port 8000   # → http://localhost:8000")


def cmd_gaps(engine: BrainEngine, args: list[str]) -> None:
    taxonomy = None
    threshold = 10
    as_json = False
    i = 0
    while i < len(args):
        if args[i] == "--taxonomy" and i + 1 < len(args):
            taxonomy = load_taxonomy(args[i + 1])
            i += 2
        elif args[i] == "--min" and i + 1 < len(args):
            # Audit #26: nicht-numerische --min-Werte → Usage-Fehler statt ValueError-Traceback.
            try:
                threshold = int(args[i + 1])
            except ValueError:
                print(f"Nutzung: --min erwartet eine Zahl, bekommen: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif args[i] == "--json":
            as_json = True
            i += 1
        else:
            i += 1
    cov = analyze_coverage(engine.brain, taxonomy)
    if as_json:
        import json as _json
        print(_json.dumps({
            "total": cov.total,
            "areas": [{"name": a.name, "count": a.count} for a in cov.areas],
            "gaps": [a.name for a in find_gaps(cov, threshold)],
            "unclassified": cov.unclassified,
        }, ensure_ascii=False, indent=2))
    else:
        print(render(cov, threshold))


def cmd_merge(engine: BrainEngine, args: list[str]) -> None:
    if len(args) != 2:
        print("Nutzung: ig merge <survivor_id> <deletee_id>  (konsolidiert deletee in survivor)")
        sys.exit(1)
    survivor, deletee = args[0], args[1]
    try:
        r = merge_nodes(engine.brain, survivor, deletee, embedder=engine.embedder)
    except ValueError as exc:
        print(f"Fehler: {exc}")
        sys.exit(1)
    print(f"merge: {r.deletee} konsolidiert in {r.survivor}")
    print(f"  Kanten umgeleitet: {r.edges_redirected} · entfernt: {r.edges_removed}")


def cmd_near_dup(engine: BrainEngine, args: list[str]) -> None:
    lo, hi, max_pairs, as_json = 0.78, 0.92, None, False
    i = 0
    while i < len(args):
        if args[i] == "--lo" and i + 1 < len(args):
            try:
                lo = float(args[i + 1])
            except ValueError:
                print(f"Nutzung: --lo erwartet eine Zahl, bekommen: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif args[i] == "--hi" and i + 1 < len(args):
            try:
                hi = float(args[i + 1])
            except ValueError:
                print(f"Nutzung: --hi erwartet eine Zahl, bekommen: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif args[i] == "--max" and i + 1 < len(args):
            try:
                max_pairs = int(args[i + 1])
            except ValueError:
                print(f"Nutzung: --max erwartet eine Zahl, bekommen: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif args[i] == "--json":
            as_json = True; i += 1
        else:
            i += 1
    # Audit #26 (Semantik): --lo >= --hi ist eine leere/invalide Band-Angabe;
    # --max 0 means "0 pairs" (a limit), not "unlimited".
    if lo >= hi:
        print(f"Nutzung: --lo ({lo}) muss kleiner als --hi ({hi}) sein.")
        sys.exit(1)
    if max_pairs is not None and max_pairs < 0:
        print("Nutzung: --max erwartet eine nicht-negative Zahl.")
        sys.exit(1)
    pairs = near_dup_pairs(engine.brain, lo=lo, hi=hi, max_pairs=max_pairs)
    if as_json:
        import json as _json
        print(_json.dumps(
            [{"score": p.score, "a": p.a, "b": p.b, "a_text": p.a_text, "b_text": p.b_text}
             for p in pairs], ensure_ascii=False, indent=2))
    else:
        print(render_near_dup(pairs))


def cmd_status(engine: BrainEngine, args: list[str]) -> None:
    as_json = "--json" in args
    if as_json:
        import json as _json
        c = connectivity(engine.brain)
        print(_json.dumps({
            "total": c.total, "edges": c.edges, "max_degree": c.max_degree,
            "mean_degree": round(c.mean_degree, 2),
            "orphans": len(c.orphans), "islands": len(c.islands), "weak": len(c.weak),
            "status": dict(status_counts(engine.brain)),
        }, ensure_ascii=False, indent=2))
    else:
        print(render_status(engine.brain))


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
    "accept": lambda e, a: _resolve_cmd(e, _first_or_usage(a, "accept"), True),
    "reject": lambda e, a: _resolve_cmd(e, _first_or_usage(a, "reject"), False),
    "link": cmd_link,
    "search": cmd_search,
    "gaps": cmd_gaps,
    "merge": cmd_merge,
    "near-dup": cmd_near_dup,
    "status": cmd_status,
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    cmd, rest = args[0], args[1:]
    fn = COMMANDS.get(cmd)
    if fn is None:
        print(f"Unknown command: {cmd}. Available: {', '.join(COMMANDS)}")
        sys.exit(1)
    fn(make_engine(), rest)


if __name__ == "__main__":
    main()
