"""Read-only MCP server (report #1): the brain as a tool for AI assistants.

stdio transport only — the brain is single-user and private; an HTTP listener
would add an auth/exposure surface for zero benefit. NO write tools: ingest
commits AND pushes to a private repo, and model-initiated writes with no human
review are the single highest-risk thing this surface could do.

Engine construction is LAZY (first tool call, not import): `list_tools` and
`brain_status` must never pay the sentence-transformers model load. The
process-wide cache in runtime.make_engine() makes the load a once-per-server
cost instead of once-per-call.
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from . import format as fmt
from ..runtime import brain_path, make_engine, reset_engine_cache

mcp = FastMCP(
    "ideagraph",
    instructions=(
        "Consult the brain before starting non-trivial design or research "
        "work; skip it for routine edits. All tools are read-only."
    ),
)


def _cache_vectors() -> bool:
    """DECIDED (2026-09-15): the MCP default is STRICTLY read-only — a
    model-initiated write into the private repo (dirty files → autostash
    churn) must not be the default, and the long-lived stdio server holds
    vectors in the process-wide engine cache anyway. IG_MCP_CACHE_VECTORS=1
    opts back in to disk-cache filling (slower first search per clone)."""
    return os.environ.get("IG_MCP_CACHE_VECTORS", "0") == "1"


def _tool(fn):
    """Register with the readOnlyHint annotation so untrusted-server clients
    skip approval prompts."""
    return mcp.tool(annotations={"readOnlyHint": True})(fn)


@_tool
def search_brain(query: str, k: int = 5) -> dict:
    """Hybrid search (dense + BM25, RRF-fused) over the knowledge brain.

    `score` is a rank-fusion score (reciprocal-rank fusion), NOT a similarity
    — do not compare it across queries or read it as a confidence.
    """
    query = (query or "").strip()
    if not query:
        return fmt.invalid("query must be a non-empty string")
    if len(query) > 500:
        return fmt.invalid("query exceeds 500 characters")
    if not isinstance(k, int) or k < 1 or k > 20:
        return fmt.invalid("k must be an integer between 1 and 20")
    brain = brain_path()
    if not os.path.isdir(brain):
        return fmt.brain_missing(brain)
    try:
        from ..retrieval import retrieve
        engine = make_engine()
        hits = retrieve(engine, query, k=k, persist=_cache_vectors())
    except RuntimeError as exc:      # embedder unavailable etc.
        return fmt.err("embedder_unavailable", str(exc)[-200:])
    except Exception as exc:         # noqa: BLE001 — the envelope contract:
        return fmt.err("internal",   # a raw traceback over JSON-RPC surfaces
                       f"{type(exc).__name__}: {exc}")  # as an opaque error
    if not hits:
        return {"ok": True, "query": query, "count": 0, "results": [],
                "hint": f"No node matched. Try fewer/more specific terms; "
                        f"the brain has {len(engine.brain.read_nodes())} nodes."}
    id2node = {n.id: n for n in engine.brain.read_nodes()}
    results = []
    for nid, score in hits:
        node = id2node.get(nid)
        if node is None:
            continue
        results.append({
            "id": node.id,
            "score": round(float(score), 4),
            "snippet": fmt.snippet(node.text),
            "status": node.status,
            "type": node.ntype,
            "tags": node.tags,
            "created": node.created,
        })
    return {"ok": True, "query": query, "count": len(results),
            "results": results}


@_tool
def get_node(id: str, max_chars: int = fmt.DEFAULT_NODE_CHARS) -> dict:
    """One node by id: full text (capped) + its live edges."""
    node_id = (id or "").strip()
    if not node_id:
        return fmt.invalid("id must be a non-empty string")
    if not isinstance(max_chars, int) or max_chars < 100 or max_chars > fmt.MAX_NODE_CHARS:
        return fmt.invalid(f"max_chars must be an integer between 100 and "
                           f"{fmt.MAX_NODE_CHARS}")
    from ..runtime import make_brain
    brain = make_brain()
    node = brain.read_node(node_id)
    if node is None:
        return fmt.node_not_found(node_id)
    text = node.text or ""
    edges = [e for e in brain.read_edges()
             if e.valid_to is None and not e.rejected
             and node_id in (e.source, e.target)]
    out_edges = []
    id2node = {n.id: n for n in brain.read_nodes()}
    for e in edges:
        other = e.target if e.source == node_id else e.source
        other_node = id2node.get(other)
        out_edges.append({
            "id": e.id,
            "kind": e.kind,
            "direction": "out" if e.source == node_id else "in",
            "other_id": other,
            "other_snippet": fmt.snippet(other_node.text, 80) if other_node else "?",
            "pending": e.pending,
            "confidence": e.confidence,
            "valid_from": e.valid_from,
            "valid_to": e.valid_to,
        })
    return {"ok": True,
            "node": {"id": node.id, "text": text[:max_chars],
                     "created": node.created, "source": node.source,
                     "sources": node.sources, "type": node.ntype,
                     "status": node.status, "tags": node.tags},
            "truncated": len(text) > max_chars,
            "text_chars": len(text),
            "edges": out_edges,
            "degree": len(out_edges)}


@_tool
def neighbors(id: str, hops: int = 1, kinds: list[str] | None = None,
              include_pending: bool = False,
              limit: int = fmt.DEFAULT_NEIGHBOR_LIMIT) -> dict:
    """Graph neighborhood of a node over UNDIRECTED live edges (1-2 hops).

    This is the graph question vector search cannot answer: what is this
    idea actually connected to?
    """
    node_id = (id or "").strip()
    if not node_id:
        return fmt.invalid("id must be a non-empty string")
    if not isinstance(hops, int) or hops < 1 or hops > 2:
        return fmt.invalid("hops must be 1 or 2")
    if not isinstance(limit, int) or limit < 1 or limit > fmt.MAX_NEIGHBOR_LIMIT:
        return fmt.invalid(f"limit must be an integer between 1 and "
                           f"{fmt.MAX_NEIGHBOR_LIMIT}")
    from ..runtime import make_brain
    from ..graph import neighbors as graph_neighbors
    brain = make_brain()
    if brain.read_node(node_id) is None:
        return fmt.node_not_found(node_id)
    found = graph_neighbors(brain, node_id, hops=hops, kinds=kinds,
                            include_pending=include_pending, limit=limit)
    kinds_present: dict[str, int] = {}
    for nb in found:
        kinds_present[nb.kind] = kinds_present.get(nb.kind, 0) + 1
    return {"ok": True, "id": node_id, "hops": hops,
            "count": len(found),
            "truncated": len(found) >= limit,
            "neighbors": [{"id": nb.id, "snippet": fmt.snippet(nb.snippet),
                           "kind": nb.kind, "direction": nb.direction,
                           "pending": nb.pending,
                           "confidence": nb.confidence, "hops": nb.hops}
                          for nb in found],
            "kinds_present": kinds_present}


@_tool
def brain_status() -> dict:
    """Cheap orientation: size, connectivity, pending-review load.

    Returns the brain path BASENAME only — the brain is private and this
    string lands in a model's context.
    """
    from ..hygiene import connectivity, status_counts
    brain_p = brain_path()
    if not os.path.isdir(brain_p):
        return fmt.brain_missing(brain_p)
    from ..runtime import make_brain
    brain = make_brain()
    conn = connectivity(brain)
    counts = status_counts(brain)
    pending = sum(1 for e in brain.read_edges() if e.pending)
    return {"ok": True, "total": conn.total, "edges": conn.edges,
            "max_degree": conn.max_degree,
            "mean_degree": round(conn.mean_degree, 2),
            "orphans": len(conn.orphans), "islands": len(conn.islands),
            "weak": len(conn.weak), "pending_edges": pending,
            "status": {k: counts.get(k, 0)
                       for k in ("active", "probation", "tombstone")},
            "brain_path_basename": os.path.basename(brain_p.rstrip("/"))}


def main() -> None:
    """Entry point (`ig mcp` / `ig-mcp`): stdio JSON-RPC, nothing else on
    stdout — stdout IS the transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
