"""Tests for the dream pass (`ideagraph/dream.py`, `ig dream`).

The consolidation half of the memory system: deterministic maintenance
(`refresh`) and community distillation (`distill`). Both must be non-destructive,
must never touch user-authored edges (`origin="manual"`), and must be idempotent
so a scheduled pass cannot duplicate work.

What is deliberately NOT here: promotion/decay gates and auto-merge. Measured on
the live brain before building: recall-gated promotion had 0 eligible nodes, a
degree gate >= 3 matched 99 % of nodes, the corpus was 27 days old, and the 97
near-dup pairs in the review band are demonstrably related-but-distinct.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ideagraph.brain import Brain, Edge, Node
from ideagraph.dream import (
    SUMMARY_TAG,
    distill,
    plan,
    refresh,
    refresh_plan,
)
from ideagraph.recall import record


def _brain(tmp_path) -> Brain:
    return Brain(str(tmp_path / "brain"), mode="local")


def _two_clusters(b: Brain) -> None:
    """Six nodes in two dense triples — LPA finds two communities."""
    for i in range(3):
        b.write_node(Node(id=f"a{i}", text=f"alpha cluster node {i}"))
        b.write_node(Node(id=f"b{i}", text=f"omega cluster node {i}"))
    edges = []
    for i in range(3):
        for j in range(i + 1, 3):
            edges.append(Edge(id=f"a{i}{j}", source=f"a{i}", target=f"a{j}",
                              kind="extends", pending=False, origin="suggester",
                              confidence=0.7))
            edges.append(Edge(id=f"b{i}{j}", source=f"b{i}", target=f"b{j}",
                              kind="extends", pending=False, origin="suggester",
                              confidence=0.7))
    b.write_edges(edges)


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

def test_plan_reports_and_writes_nothing(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)
    before_nodes = sorted(n.id for n in b.read_nodes())
    before_edges = len(b.read_edges(include_rejected=True))

    result = plan(b, min_community=2)

    assert result.nodes == 6
    assert len(result.distill_candidates) == 2
    assert sorted(n.id for n in b.read_nodes()) == before_nodes
    assert len(b.read_edges(include_rejected=True)) == before_edges
    assert "DREAM PLAN" in result.render()
    assert "Nothing written" in result.render() or "dry run" in result.render()


def test_plan_promotion_needs_recall_and_degree(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)
    # a0 has degree 2 and no recalls -> not eligible under min_degree=2/min_recall=1
    assert plan(b, min_recall=1, min_degree=2, min_community=2).promotion_candidates == []

    record(b, "q", ["a0"])
    refresh(b)
    assert plan(b, min_recall=1, min_degree=2, min_community=2).promotion_candidates == ["a0"]


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------

def test_refresh_rederives_drifted_suggester_kind(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    b.write_node(Node(id="b", text="Thema B"))
    b.write_edges([
        Edge(id="s1", source="a", target="b", kind="extends", pending=False,
             confidence=0.9, origin="suggester"),      # drifted: 0.9 means `similar`
        Edge(id="m1", source="b", target="a", kind="extends", pending=False,
             confidence=0.9, origin="manual"),         # user-authored: untouchable
    ])

    res = refresh(b)

    assert res["kind_changes"] == 1
    kinds = {e.id: e.kind for e in b.read_edges()}
    assert kinds["s1"] == "similar"
    assert kinds["m1"] == "extends", "manual edges are never rewritten"


def test_refresh_is_idempotent(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    b.write_node(Node(id="b", text="Thema B"))
    b.write_edges([Edge(id="s1", source="a", target="b", kind="extends", pending=False,
                        confidence=0.9, origin="suggester")])

    assert refresh(b)["kind_changes"] == 1
    assert refresh(b)["kind_changes"] == 0


def test_refresh_folds_the_recall_ledger(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    record(b, "frage", ["a"])

    res = refresh(b)

    assert res["recalls"] == 1 and res["recall_nodes"] == 1
    assert {n.id: n.recall_count for n in b.read_nodes()}["a"] == 1


def test_refresh_dry_run_writes_nothing(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    b.write_node(Node(id="b", text="Thema B"))
    b.write_edges([Edge(id="s1", source="a", target="b", kind="extends", pending=False,
                        confidence=0.9, origin="suggester")])

    res = refresh(b, dry_run=True)

    assert res["kind_changes"] == 1, "a dry run reports what it WOULD change"
    assert {e.id: e.kind for e in b.read_edges()}["s1"] == "extends", "and writes nothing"


def test_refresh_plan_counts_mismatches(tmp_path):
    b = _brain(tmp_path)
    b.write_node(Node(id="a", text="Thema A"))
    b.write_node(Node(id="b", text="Thema B"))
    b.write_edges([Edge(id="s1", source="a", target="b", kind="extends", pending=False,
                        confidence=0.9, origin="suggester")])

    assert refresh_plan(b)["kind_mismatches"] == 1


# ---------------------------------------------------------------------------
# distill
# ---------------------------------------------------------------------------

def test_distill_writes_one_summary_per_community(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)

    res = distill(b, min_size=2, members_per_summary=2)

    assert res["summaries"] == 2 and res["edges"] == 4
    summaries = [n for n in b.read_nodes() if SUMMARY_TAG in (n.tags or [])]
    assert len(summaries) == 2
    for node in summaries:
        assert node.status == "active"
        assert "Community abstraction" in node.text
        assert "consolidator summary" in node.text
    consolidator = [e for e in b.read_edges() if e.origin == "consolidator"]
    assert len(consolidator) == 4
    assert all(e.kind == "extends" and not e.pending for e in consolidator)
    # every summary points at real members of its own community
    ids = {n.id for n in summaries}
    for edge in consolidator:
        assert edge.source in ids and edge.target not in ids


def test_distill_is_idempotent(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)

    first = distill(b, min_size=2, members_per_summary=2)
    second = distill(b, min_size=2, members_per_summary=2)

    assert first["summaries"] == 2
    assert second["summaries"] == 0 and second["edges"] == 0
    assert len([n for n in b.read_nodes() if SUMMARY_TAG in (n.tags or [])]) == 2


def test_distill_respects_min_size_and_limit(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)

    assert distill(b, min_size=4)["summaries"] == 0
    assert distill(b, min_size=2, limit=1)["summaries"] == 1


def test_distill_dry_run_writes_nothing(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)

    res = distill(b, min_size=2, dry_run=True)

    assert res["summaries"] == 2 and res["edges"] == 0
    assert [n for n in b.read_nodes() if SUMMARY_TAG in (n.tags or [])] == []


def test_distill_uses_the_summarizer_seam(tmp_path):
    b = _brain(tmp_path)
    _two_clusters(b)
    seen = []

    def fake_llm(digest: str) -> str:
        seen.append(digest)
        return "MODEL SUMMARY: " + digest.splitlines()[0]

    res = distill(b, min_size=2, members_per_summary=2, summarizer=fake_llm)

    assert res["used_llm"] is True and res["summaries"] == 2
    assert len(seen) == 2, "the model sees the same extractive evidence"
    texts = [n.text for n in b.read_nodes() if SUMMARY_TAG in (n.tags or [])]
    assert all(t.startswith("MODEL SUMMARY: Community abstraction") for t in texts)


def test_distill_commits_once_per_pass(tmp_path, monkeypatch):
    b = _brain(tmp_path)
    _two_clusters(b)
    calls = []
    monkeypatch.setattr(b, "commit_and_push",
                        lambda message, push=True: calls.append(message))

    distill(b, min_size=2, members_per_summary=2)

    assert len(calls) == 1 and "2 community summaries" in calls[0]