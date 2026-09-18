"""CLI for the brain: init, ingest, pending, accept, reject, link, search.

Examples:
  python -m ideagraph init [--remote <brain-repo-url>] [--demo]
  python -m ideagraph ingest "New idea ..." [--source agent/bot] [--allow-dup]
  cat note.md | python -m ideagraph ingest -
  python -m ideagraph pending
  python -m ideagraph accept <edge_id>
  python -m ideagraph reject <edge_id>
  python -m ideagraph accept-pending [--max-intent-per-source 2] [--dry-run] [--json]
  python -m ideagraph link <node_a> <node_b> [--kind same_as]
  python -m ideagraph search "attention" [--json]
  python -m ideagraph gaps [--taxonomy tax.json] [--min 10] [--json]
  python -m ideagraph merge <survivor_id> <deletee_id>   # consolidate a near-dup
  python -m ideagraph near-dup [--lo 0.78] [--hi 0.92]   # report near-duplicate pairs
  python -m ideagraph status [--json]                    # connectivity/hygiene report

Env like the server: IG_BRAIN_PATH, IG_BRAIN_REMOTE, IG_BRAIN_MODE,
IDEAGRAPH_EMBEDDER (st|hash), IDEAGRAPH_EMBEDDER_MODEL.
"""

from __future__ import annotations

import sys

from . import runtime
from .brain_engine import BrainEngine
from .gaps import analyze_coverage, find_gaps, render, load_taxonomy
from .hygiene import near_dup_pairs, connectivity, status_counts, render_near_dup, render_status
from .merge import merge_nodes
from .retrieval import retrieve

# Shared factory (one source of truth for CLI, server and future MCP surface).
make_engine = runtime.make_engine


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
                print("Usage: ig ingest \"text\" --source <source>")
                sys.exit(1)
            source = args[i + 1]
            i += 2
        elif args[i] == "--allow-dup":
            allow_dup = True
            i += 1
        else:
            rest.append(args[i])
            i += 1
    # Audit #32: '-' is the stdin marker, also in mixed args. Before,
    # 'ig ingest - extra' used to ingest the literal text "- extra"
    # (exit 0, node created). A '-' token means stdin; extra text
    # next to it is an error.
    if "-" in rest:
        if len(rest) > 1:
            print("Usage: '-' (stdin) cannot be combined with text arguments.")
            sys.exit(1)
        text = sys.stdin.read()
    else:
        text = " ".join(rest)
    if not text.strip():
        print("Nothing to ingest. Usage: ig ingest \"text\" | ig ingest - < file")
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
    """Audit #26: a missing positional argument prints the usage line
    instead of raising IndexError."""
    if not args:
        print(f"Usage: ig {cmd} <edge_id>")
        sys.exit(1)
    return args[0]


def _resolve_cmd(engine: BrainEngine, edge_id: str, accept: bool) -> None:
    edge = engine.resolve(edge_id, accept)
    if edge is None:
        print(f"Edge {edge_id} not found or not pending.")
        sys.exit(1)
    print(f"{'accepted' if accept else 'rejected'}: {edge_id} [{edge.kind}]")


def cmd_link(engine: BrainEngine, args: list[str]) -> None:
    kind = "same_as"
    if "--kind" in args:
        i = args.index("--kind")
        # Audit #26: a missing value after --kind is a usage error, not an IndexError.
        if i + 1 >= len(args):
            print("Usage: ig link <node_a> <node_b> [--kind same_as]")
            sys.exit(1)
        kind = args[i + 1]
        args = args[:i] + args[i + 2:]
    if len(args) != 2:
        print("Usage: ig link <node_a> <node_b> [--kind same_as]")
        sys.exit(1)
    try:
        edge = engine.link(args[0], args[1], kind)
    except ValueError as exc:
        print(f"Error: {exc}")
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
            # Audit #58: friendly message instead of a raw traceback — a
            # non-empty directory is never overwritten.
            print(f"Error: {brain.path} already exists and is not empty.")
            print("The demo brain is never written into an existing directory.")
            print("Choose a different path: IG_BRAIN_PATH=<path> ig init --demo")
            sys.exit(1)
        print(f"✓ Demo brain initialized: {brain.path}")
        print(f"  {stats['nodes']} nodes · {stats['edges']} edges "
              f"({stats['pending']} pending for HITL review)")
        print("  Includes: all edge types, 1 orphan island (demos `ig status`),")
        print("  1 near-dup pair (demos `ig near-dup` + `ig merge`), 1 same_as pair.")
        print("Try it out:")
        print("  ig status                     # island + hygiene report")
        print("  ig near-dup                   # find the demo near-dup pair")
        print("  ig pending                    # review the 2 pending suggestions")
        print("  ig search \"RAG\"               # hybrid search (works instantly)")
        print("  uvicorn ideagraph.server:app --port 8000   # → http://localhost:8000")
        return
    if (brain.path / "INDEX.md").exists() or (brain.path / "nodes").exists():
        # same #58 principle for plain init: never clobber an existing brain
        print(f"Error: {brain.path} already contains a brain.")
        print("Choose a different path: IG_BRAIN_PATH=<path> ig init")
        sys.exit(1)
    brain.init(remote=remote, commit=True)
    print(f"✓ Brain repo initialized: {brain.path}")
    mode_line = f"  Mode: {brain.mode}"
    mode_line += (f" · Remote: {remote}" if remote else " (local, no remote)")
    print(mode_line)
    print("  Structure: nodes/ · edges.jsonl · vectors.jsonl · INDEX.md")
    print("Get started:")
    print('  ig ingest "First idea ..."            # CLI ingest')
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
            # Audit #26: non-numeric --min values are a usage error, not a ValueError traceback.
            try:
                threshold = int(args[i + 1])
            except ValueError:
                print(f"Usage: --min expects a number, got: {args[i + 1]!r}")
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


def cmd_communities(engine: BrainEngine, args: list[str]) -> None:
    """Read-only topology report: communities, god nodes, structural gaps."""
    from .communities import analyze_communities, render_communities

    min_size = 15
    top = 10
    betweenness_sample: int | None = None
    include_pending = True
    with_members = False
    as_json = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--min-size" and i + 1 < len(args):
            try:
                min_size = int(args[i + 1])
            except ValueError:
                print(f"Usage: --min-size expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif arg == "--top" and i + 1 < len(args):
            try:
                top = int(args[i + 1])
            except ValueError:
                print(f"Usage: --top expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif arg == "--betweenness-sample" and i + 1 < len(args):
            try:
                betweenness_sample = int(args[i + 1])
            except ValueError:
                print(f"Usage: --betweenness-sample expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif arg == "--no-pending":
            include_pending = False
            i += 1
        elif arg == "--members":
            with_members = True
            i += 1
        elif arg == "--json":
            as_json = True
            i += 1
        else:
            i += 1
    rep = analyze_communities(engine.brain, min_size=min_size, top=top,
                              betweenness_sample=betweenness_sample,
                              include_pending=include_pending,
                              with_members=with_members)
    if as_json:
        import json as _json
        payload = {
            "nodes": rep.nodes,
            "edges": rep.edges,
            "modularity": round(rep.modularity, 4),
            "betweenness_sample": rep.betweenness_sample,
            "communities": [{
                "id": c.id,
                "size": c.size,
                "degree_sum": c.degree_sum,
                "internal_edges": c.internal_edges,
                "label": c.label,
                "sample": c.sample,
                **({"members": c.members} if with_members else {}),
            } for c in rep.communities],
            "god_nodes": [{
                "id": g.id, "degree": g.degree,
                "betweenness": g.betweenness, "text": g.text,
            } for g in rep.god_nodes],
            "gaps": [{
                "a": g.a, "b": g.b,
                "a_label": g.a_label, "b_label": g.b_label,
                "a_size": g.a_size, "b_size": g.b_size,
                "observed_edges": g.observed_edges,
                "expected_edges": g.expected_edges,
                "deficit": g.deficit,
                "bridge_nodes": g.bridge_nodes,
                "a_samples": g.a_samples, "b_samples": g.b_samples,
            } for g in rep.gaps],
            "isolated": rep.isolated,
            "unclassified": rep.unclassified,
        }
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_communities(rep))


def cmd_report(engine: BrainEngine, args: list[str]) -> None:
    """One-page state-of-the-brain digest (read-only)."""
    from .report import render_report, report_data
    import json as _json

    since = None
    top = None
    as_json = False
    write = False
    coverage = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--since" and i + 1 < len(args):
            since = args[i + 1]
            i += 2
        elif arg == "--top" and i + 1 < len(args):
            try:
                top = int(args[i + 1])
            except ValueError:
                print(f"Usage: --top expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif arg == "--json":
            as_json = True
            i += 1
        elif arg == "--write":
            write = True
            i += 1
        elif arg == "--coverage":
            coverage = True
            i += 1
        else:
            i += 1
    opts: dict = {}
    if since is not None:
        # Accept hours (int/float) or ISO — reject anything else BEFORE doing
        # any work (usage error, not a traceback mid-render).
        from .report import _parse_since
        try:
            _parse_since({"since": since})
        except (ValueError, TypeError):
            print(f"Usage: --since expects hours (e.g. 24) or ISO datetime, "
                  f"got: {since!r}")
            sys.exit(1)
        opts["since"] = since
    if top is not None:
        opts["top"] = top
    if coverage:
        opts["coverage"] = True
    if as_json:
        print(_json.dumps(report_data(engine.brain, **opts),
                          ensure_ascii=False, indent=2))
    else:
        out = render_report(engine.brain, **opts)
        # A blank generated artifact destroys the workflow value (Graphify
        # GRAPH_REPORT.md lesson): guard the body at runtime.
        if len(out.strip()) < 50:
            print("Error: report body is empty — the brain may be unreadable")
            sys.exit(1)
        print(out)
    if write:
        from .report import write_report
        try:
            write_report(engine.brain, **opts)
        except RuntimeError as exc:
            print(f"Error: {exc}")
            sys.exit(1)
        if engine.brain.mode == "git":
            engine.brain.commit_and_push("report: regenerate BRAIN_REPORT.md")
            print("written: BRAIN_REPORT.md (committed)")
        else:
            print("written: BRAIN_REPORT.md (local mode, no commit)")


def cmd_merge(engine: BrainEngine, args: list[str]) -> None:
    if len(args) != 2:
        print("Usage: ig merge <survivor_id> <deletee_id>  (consolidates deletee into survivor)")
        sys.exit(1)
    survivor, deletee = args[0], args[1]
    try:
        r = merge_nodes(engine.brain, survivor, deletee, embedder=engine.embedder)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    print(f"merge: {r.deletee} consolidated into {r.survivor}")
    print(f"  edges redirected: {r.edges_redirected} · removed: {r.edges_removed}")


def cmd_near_dup(engine: BrainEngine, args: list[str]) -> None:
    lo, hi, max_pairs, as_json = 0.78, 0.92, None, False
    i = 0
    while i < len(args):
        if args[i] == "--lo" and i + 1 < len(args):
            try:
                lo = float(args[i + 1])
            except ValueError:
                print(f"Usage: --lo expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif args[i] == "--hi" and i + 1 < len(args):
            try:
                hi = float(args[i + 1])
            except ValueError:
                print(f"Usage: --hi expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif args[i] == "--max" and i + 1 < len(args):
            try:
                max_pairs = int(args[i + 1])
            except ValueError:
                print(f"Usage: --max expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            i += 2
        elif args[i] == "--json":
            as_json = True; i += 1
        else:
            i += 1
    # Audit #26 (Semantik): --lo >= --hi ist eine leere/invalide Band-Angabe;
    # --max 0 means "0 pairs" (a limit), not "unlimited".
    if lo >= hi:
        print(f"Usage: --lo ({lo}) must be smaller than --hi ({hi}).")
        sys.exit(1)
    if max_pairs is not None and max_pairs < 0:
        print("Usage: --max expects a non-negative number.")
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
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if not args:
        print("Usage: ig search <term> [--json]")
        sys.exit(1)
    q = " ".join(args)
    id2node = {n.id: n for n in engine.brain.read_nodes()}
    hits = retrieve(engine, q, k=5)
    if as_json:
        import json as _json
        results = []
        for nid, score in hits:
            n = id2node.get(nid)
            if n is None:
                continue
            results.append({
                "id": nid,
                # RRF rank-fusion score, NOT a similarity — do not compare
                # it across queries or read it as a confidence.
                "score": round(score, 4),
                "snippet": _short(n.text, 200),
                "status": n.status,
                "type": n.ntype,
                "tags": list(n.tags or []),
                "created": n.created,
            })
        print(_json.dumps({"query": q, "count": len(results), "results": results},
                          ensure_ascii=False, indent=2))
        return
    for nid, score in hits:
        n = id2node.get(nid)
        if n is not None:
            print(f"{nid}  {score:.3f}  {_short(n.text)}")
    print(f"\n{len(hits)} hits (hybrid dense+BM25)")


def cmd_mcp(engine: BrainEngine, args: list[str]) -> None:
    """Read-only MCP server over stdio (report #1)."""
    try:
        from .mcp.server import main as mcp_main
    except ImportError:
        print("MCP support is not installed — pip install 'ideagraph-live[mcp]'")
        sys.exit(1)
    mcp_main()


def cmd_accept_pending(engine: BrainEngine, args: list[str]) -> None:
    """Review policy: accept pending suggestions, cap intent fan-out per source.

    Non-intent pending edges are accepted; intent edges beyond
    `--max-intent-per-source` (default 2, env IG_INTENT_AUTO_ACCEPT_MAX) stay
    pending for `ig pending`. One commit for the whole batch.
    """
    max_intent, dry_run, as_json = None, False, False
    i = 0
    while i < len(args):
        if args[i] == "--max-intent-per-source" and i + 1 < len(args):
            try:
                max_intent = int(args[i + 1])
            except ValueError:
                print(f"Usage: --max-intent-per-source expects a number, got: {args[i + 1]!r}")
                sys.exit(1)
            if max_intent < 0:
                print("Usage: --max-intent-per-source must be >= 0")
                sys.exit(1)
            i += 2
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        elif args[i] == "--json":
            as_json = True
            i += 1
        else:
            print(f"Unknown option for accept-pending: {args[i]!r}")
            sys.exit(1)
    from .review import accept_pending
    res = accept_pending(engine.brain, max_intent_per_source=max_intent,
                         dry_run=dry_run)
    if as_json:
        import json as _json
        print(_json.dumps(res, ensure_ascii=False, indent=2))
        return
    verb = "would accept" if dry_run else "accepted"
    print(f"{verb} {len(res['accepted'])} pending edge(s); "
          f"held {len(res['held'])} intent edge(s) for review "
          f"(cap {res['cap']} per source)")
    if res["held"]:
        print("Review them with: ig pending")


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
    "communities": cmd_communities,
    "report": cmd_report,
    "mcp": cmd_mcp,
    "accept-pending": cmd_accept_pending,
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
