"""The dream pass: what the brain does when nobody is ingesting.

The ingest half of this engine is strong (dedupe, typed edges, provenance,
evals). The other half of a memory system — consolidation — was missing: nothing
promoted, nothing decayed, nothing was ever distilled, `consolidate()` was dead
code. This module is that half, split into three explicitly requested steps so
nothing happens implicitly:

    plan()     — the eligibility report (`ig dream` / `--dry-run`). No writes.
                 Every gate is a flag; the numbers tell you what a pass WOULD do
                 before it does anything.
    refresh()  — deterministic maintenance: re-derive similarity kinds from the
                 stored cosine (suggester edges only — manual edges are
                 user-authored), fold the recall ledger, rebuild INDEX, refresh
                 BRAIN_REPORT. Never destructive.
    distill()  — one abstraction node per community (extractive by default;
                 `summarizer=` / `--llm` swaps in a model). Marked
                 `origin="consolidator"` so the next pass can tell what a pass
                 wrote.

Reference points (both are the same shape): OpenClaw's dreaming (light/REM/deep,
promotion only through gates, consolidation turn that merges duplicates and
retires superseded entries) and the Hermes curator (deterministic transitions
that never delete, pinned/cron-referenced entries protected, LLM consolidation
OFF by default). Measured on the live brain before building this: recall-gated
promotion had 0 eligible nodes, a degree gate >= 3 matched 99 % of nodes, and the
corpus was 27 days old — so promotion/decay gates are NOT part of this pass yet;
they wait for a real recall distribution. The merge axis (97 pairs in the review
band) is a REVIEW list, not an auto-merge: the top pairs are demonstrably
related-but-distinct.
"""

from __future__ import annotations

import collections
import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from typing import Callable

from .brain import Brain, Edge, Node
from .communities import analyze_communities
from .hygiene import connectivity, near_dup_pairs
from .intent import INTENT_KINDS
from .similarity import cosine

# Similarity kinds are re-derived from the stored cosine with the band rule the
# suggester uses (`suggester.py`): >= 0.75 same topic, below that builds-on.
SIMILAR_BAND = 0.75
# Communities of at least this size are distillable; a pass writes at most
# `DREAM_MAX_DISTILL` summary nodes so one run stays reviewable.
DREAM_MIN_COMMUNITY = 10
DREAM_MAX_DISTILL = 10
# Members a summary links to (strongest by degree inside the community).
DREAM_MEMBERS_PER_SUMMARY = 5
SUMMARY_TAG = "community-summary"


@dataclass
class DreamPlan:
    """What a pass WOULD do under the given gates (nothing written)."""

    nodes: int = 0
    edges: int = 0
    promotion_candidates: list[str] = field(default_factory=list)
    decay_candidates: list[str] = field(default_factory=list)
    merge_candidates: list[tuple[str, str, float]] = field(default_factory=list)
    distill_candidates: list[tuple[int, int]] = field(default_factory=list)  # (cid, size)
    refresh: dict = field(default_factory=dict)

    def render(self) -> str:
        lines = ["# DREAM PLAN (dry run — nothing written)", ""]
        lines.append(f"brain: {self.nodes} live nodes · {self.edges} live edges")
        lines.append("")
        lines.append(f"## Promotion candidates: {len(self.promotion_candidates)}")
        lines.append(f"## Decay candidates: {len(self.decay_candidates)}")
        lines.append(f"## Merge candidates (review, never auto): {len(self.merge_candidates)}")
        for a, b, score in self.merge_candidates[:5]:
            lines.append(f"  {score:.3f}  {a!r}")
            lines.append(f"           {b!r}")
        lines.append(f"## Distill candidates: {len(self.distill_candidates)} communities")
        for cid, size in self.distill_candidates[:10]:
            lines.append(f"  C{cid}  size {size}")
        lines.append("## Refresh")
        for key, value in sorted(self.refresh.items()):
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)


def plan(brain: Brain, *, min_recall: int = 3, min_degree: int = 5,
         stale_days: int = 30, min_community: int = DREAM_MIN_COMMUNITY,
         merge_band: tuple[float, float] = (0.78, 0.92)) -> DreamPlan:
    """Eligibility report for every axis. Read-only."""
    nodes = {n.id: n for n in brain.read_nodes() if n.status != "tombstone"}
    edges = [e for e in brain.read_edges(include_rejected=True)
             if not e.pending and not e.rejected and e.valid_to is None]
    degree = collections.Counter()
    for e in edges:
        degree[e.source] += 1
        degree[e.target] += 1

    promotion = [nid for nid, n in nodes.items()
                 if getattr(n, "recall_count", 0) >= min_recall
                 and degree.get(nid, 0) >= min_degree]
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)

    def age_days(node: Node) -> float:
        try:
            t = datetime.datetime.fromisoformat((node.created or "").replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        return (now - t).total_seconds() / 86400

    decay = [nid for nid, n in nodes.items()
             if getattr(n, "recall_count", 0) == 0
             and degree.get(nid, 0) <= 2
             and age_days(n) >= stale_days]

    merges = [(f"{nodes[p.a].text.split(chr(10))[0][:46]}"
               if p.a in nodes else p.a,
               f"{nodes[p.b].text.split(chr(10))[0][:46]}"
               if p.b in nodes else p.b, p.score)
              for p in near_dup_pairs(brain, lo=merge_band[0], hi=merge_band[1])]
    rep = analyze_communities(brain, min_size=min_community, top=DREAM_MAX_DISTILL,
                              exclude_ids=_summary_ids(brain))
    distill = [(c.id, c.size) for c in rep.communities if c.size >= min_community]

    refresh = refresh_plan(brain)
    return DreamPlan(nodes=len(nodes), edges=len(edges),
                     promotion_candidates=promotion, decay_candidates=decay,
                     merge_candidates=merges, distill_candidates=distill,
                     refresh=refresh)


def refresh_plan(brain: Brain) -> dict:
    """What `refresh()` would change (read-only)."""
    from .recall import read_ledger
    edges = [e for e in brain.read_edges(include_rejected=True)
             if not e.pending and not e.rejected and e.valid_to is None]
    mismatched = [e for e in edges
                  if e.origin == "suggester" and e.confidence is not None
                  and e.kind in ("extends", "similar")
                  and e.kind != _expected_kind(e.confidence)]
    conn = connectivity(brain)
    return {
        "kind_mismatches": len(mismatched),
        "islands": len(conn.islands),
        "orphans": len(conn.orphans),
        "recall_ledger_entries": len(read_ledger(brain)),
    }


def _expected_kind(confidence: float) -> str:
    return "similar" if confidence >= SIMILAR_BAND else "extends"


def refresh(brain: Brain, *, dry_run: bool = False, commit: bool = True) -> dict:
    """Deterministic maintenance. Never destructive, never touches manual edges.

    1. Re-derive the kind of SUGGESTER similarity edges from the stored cosine
       (the band rule). Manual edges keep whatever kind the user chose — that is
       the whole point of the provenance field.
    2. Fold the recall ledger into the node counters (`recall.aggregate`).
    3. Rebuild INDEX.md and regenerate the tracked BRAIN_REPORT.md.
    One commit for the whole pass.
    """
    from .recall import aggregate as aggregate_recalls
    from .report import write_report

    changed = []
    edges = brain.read_edges(include_rejected=True)
    for edge in edges:
        if (edge.origin == "suggester" and edge.confidence is not None
                and edge.kind in ("extends", "similar")
                and edge.valid_to is None and not edge.rejected):
            expected = _expected_kind(edge.confidence)
            if edge.kind != expected:
                changed.append((edge.id, edge.kind, expected))
                if not dry_run:
                    edge.kind = expected
    if changed and not dry_run:
        brain.write_edges(edges)

    recall_res = {"nodes": 0, "recalls": 0}
    if not dry_run:
        recall_res = aggregate_recalls(brain, commit=False)
        brain.rebuild_index()
        try:
            write_report(brain, write=True)
        except Exception:
            # A report failure must never fail the pass (same rule as the cycle).
            pass
        if commit:
            brain.commit_and_push(
                f"dream refresh: {len(changed)} kind(s) re-derived, "
                f"{recall_res['recalls']} recall(s) folded, INDEX + report refreshed")

    return {"kind_changes": len(changed), "kinds": changed[:10],
            "recall_nodes": recall_res["nodes"], "recalls": recall_res["recalls"],
            "dry_run": dry_run}


def _summary_ids(brain: Brain) -> set[str]:
    """Ids of nodes a previous pass wrote — excluded from the next partition."""
    return {n.id for n in brain.read_nodes() if SUMMARY_TAG in (n.tags or [])}


def distill(brain: Brain, *, min_size: int = DREAM_MIN_COMMUNITY,
            limit: int = DREAM_MAX_DISTILL, members_per_summary: int = DREAM_MEMBERS_PER_SUMMARY,
            summarizer: Callable[[str], str] | None = None,
            dry_run: bool = False, commit: bool = True) -> dict:
    """One abstraction node per community — the actual "dreaming" step.

    Extractive by default (deterministic, free, reproducible): the digest names
    the community size, its dominant taxonomy area, the internal edge mix and its
    strongest members. `summarizer=` swaps in a model (the CLI wires `--llm`);
    the digest is then handed to it as the prompt, so the model sees the same
    evidence the extractive path uses.

    Idempotent: the summary id is derived from the member set, so a second pass
    over an unchanged community finds the node and skips it. Summary nodes are
    `status="active"` (a distillation is a deliberate consolidation act) and
    carry the `community-summary` tag; their edges are `origin="consolidator"`.
    """
    nodes = {n.id: n for n in brain.read_nodes() if n.status != "tombstone"}
    edges = [e for e in brain.read_edges(include_rejected=True)
             if not e.pending and not e.rejected and e.valid_to is None]
    degree: collections.Counter = collections.Counter()
    for e in edges:
        degree[e.source] += 1
        degree[e.target] += 1

    rep = analyze_communities(brain, min_size=min_size, top=limit, with_members=True,
                              exclude_ids=_summary_ids(brain))
    candidates = [c for c in rep.communities if c.size >= min_size][:limit]

    summaries = 0
    new_edges: list[Edge] = []
    for community in candidates:
        members = [m for m in community.members if m in nodes]
        if not members:
            continue
        summary_id = _summary_id(members)
        if summary_id in nodes:
            continue  # already distilled (idempotent)
        digest = _community_digest(brain, members, nodes, degree, edges, community.label)
        text = summarizer(digest) if summarizer is not None else digest
        summaries += 1
        if dry_run:
            continue
        brain.write_node(Node(id=summary_id, text=text, source="consolidator",
                              tags=[SUMMARY_TAG], ntype="semantic", status="active"))
        nodes[summary_id] = Node(id=summary_id, text=text)
        strongest = sorted(members, key=lambda m: (-degree.get(m, 0), m))[:members_per_summary]
        for member in strongest:
            new_edges.append(Edge(source=summary_id, target=member, kind="extends",
                                  pending=False, origin="consolidator"))

    if new_edges and not dry_run:
        all_edges = brain.read_edges(include_rejected=True) + new_edges
        brain.write_edges(all_edges)
        brain.rebuild_index()
        if commit:
            brain.commit_and_push(
                f"dream distill: {summaries} community summar{'y' if summaries == 1 else 'ies'}, "
                f"{len(new_edges)} consolidator edges")

    return {"summaries": summaries, "edges": len(new_edges),
            "communities": len(candidates), "used_llm": summarizer is not None,
            "dry_run": dry_run}


def _community_digest(brain: Brain, member_ids: list[str], nodes: dict[str, Node],
                      degree: collections.Counter, edges: list[Edge],
                      dominant_area: str) -> str:
    """Deterministic (extractive) digest of a community — the default summary."""
    member_set = set(member_ids)
    members = [nodes[m] for m in member_ids if m in nodes]
    hubs = sorted(member_ids, key=lambda m: -degree.get(m, 0))[:8]
    # The edge-mix census counts every non-rejected edge (pending included):
    # it describes what the community looks like, it is not a validity claim.
    census_edges = brain.read_edges(include_rejected=True)
    kinds = collections.Counter(e.kind for e in census_edges
                                if e.source in member_set or e.target in member_set)
    titles = [nodes[h].text.split("\n")[0][:90] for h in hubs if h in nodes]
    mix = ", ".join(f"{k} {v}" for k, v in kinds.most_common(6)) or "none yet"
    lines = [
        f"Community abstraction ({len(members)} nodes, dominant area: {dominant_area}).",
        f"Edge mix inside the community: {mix}.",
        "Strongest members:",
    ]
    lines += [f"- {t}" for t in titles[:5]]
    lines.append("This node is a consolidator summary: it exists to make the "
                 "community retrievable as a unit, not to replace its members.")
    return "\n".join(lines)


def _summary_id(member_ids: list[str]) -> str:
    """Deterministic id from the member set: re-running a pass is idempotent."""
    digest = hashlib.sha1("|".join(sorted(member_ids)).encode("utf-8")).hexdigest()
    return "c" + digest[:11]