"""Generated state-of-the-brain digest (BRAIN_REPORT).

One page answering: what changed since last time, what needs a human
decision, and where is the graph structurally thin. Pure read-only over
nodes/*.md frontmatter, edges.jsonl and the precomputed vectors.jsonl —
nothing here writes to the brain, embeds, or calls `ig search` (that
would re-embed; the report must stay cheap and side-effect free).

Deliberately NOT regenerated on ingest: INDEX.md already rides the
ingest RMW chain, and the coverage pass alone costs ~5.8 s on a live
brain. Staleness is stated explicitly in the header (head_sha +
commits_behind) instead of hidden.
"""
from __future__ import annotations


def render_report(brain, **opts) -> str:
    """Render the human-readable digest. (RED-SPEC STUB)"""
    return ""


def report_data(brain, **opts) -> dict:
    """Machine-readable payload for --json and GET /api/report. (STUB)"""
    return {}
