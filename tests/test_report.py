"""Tests for the generated BRAIN_REPORT digest (report #7).

All asserted numbers are measured on deterministic fixtures (pinned ids,
HashEmbedder) — never on live data. The escaping test CONSTRUCTS the pipe
case because live pipes all fall past the 60-char truncation.
"""
from __future__ import annotations

import json
import shutil
import tempfile

from ideagraph.brain import Brain, Edge, Node
from ideagraph.brain_engine import BrainEngine
from ideagraph.embedder import HashEmbedder
from ideagraph.report import render_report, report_data, _md_cell


def _engine() -> BrainEngine:
    td = tempfile.TemporaryDirectory()
    eng = BrainEngine(Brain(td.name, mode="local"), HashEmbedder())
    eng.brain._td = td
    return eng


def _teardown(eng: BrainEngine):
    td = getattr(eng.brain, "_td", None)
    if td is not None:
        shutil.rmtree(td.name, ignore_errors=True)
        td.cleanup()


def _add_edges(brain: Brain, *edges: Edge) -> None:
    brain.write_edges(edges=list(brain.read_edges()) + list(edges))


def test_report_non_empty_with_all_mandatory_sections():
    eng = _engine()
    try:
        eng.ingest("Die Erde ist eine Scheibe", source="agent/test")
        eng.ingest("Die Erde ist keine Scheibe", source="agent/test")
        out = render_report(eng.brain)
        assert len(out) >= 200  # never a blank artifact
        for header in ("# BRAIN_REPORT", "## Edge mix",
                       "## Intent review queue", "## Hubs", "## Hygiene",
                       "## Research next"):
            assert header in out, f"missing section {header!r}"
        # the intent row carries the proven contradiction source
        assert "contradicts" in out
        assert "Die Erde ist keine Scheibe" in out
        # provenance is present
        assert "generated:" in out
    finally:
        _teardown(eng)


def test_report_empty_brain_valid_and_zeroed():
    eng = _engine()
    try:
        out = render_report(eng.brain)
        assert "0 nodes / 0 live edges" in out
        assert "ZeroDivision" not in out
        data = report_data(eng.brain)
        assert data["nodes"] == 0 and data["edges"] == 0
        assert data["deltas"]["nodes"] == 0
    finally:
        _teardown(eng)


def test_md_cell_truncates_first_then_escapes():
    # Audit #55 order: truncate FIRST, then escape. A pipe AFTER char 60
    # must be cut away, not escaped; a pipe WITHIN the first 60 chars
    # must render as \|.
    text = "a" * 50 + "|tail after sixty chars is cut off anyway"
    cell = _md_cell(text, 60)
    assert "\\|" in cell          # the pipe at position 51 survives, escaped
    assert len(cell.replace("\\|", "|")) <= 60
    late = "x" * 60 + "|late pipe"
    assert "\\|" not in _md_cell(late, 60)  # truncated away before escaping
    assert _md_cell(late, 60) == "x" * 60


def test_report_json_shape_and_top_cap():
    eng = _engine()
    try:
        eng.ingest("Die Erde ist eine Scheibe", source="agent/test")
        eng.ingest("Die Erde ist keine Scheibe", source="agent/test")
        data = report_data(eng.brain, top=1)
        for key in ("generated_at", "head_sha", "nodes", "edges", "deltas",
                    "kinds", "confidence_bands", "intent_queue", "hubs",
                    "degree_percentiles", "hygiene", "research_next"):
            assert key in data, f"missing key {key}"
        assert len(data["intent_queue"]) <= 1
        assert len(data["hubs"]) <= 1
        json.dumps(data)  # must be serializable
    finally:
        _teardown(eng)


def test_report_intent_queue_groups_by_source_fanout():
    eng = _engine()
    try:
        # three targets + one source emitting 3 intent edges (fan-out 3)
        ids = []
        for i in range(4):
            n = Node(id=f"n{i}", text=f"intent target node {i}")
            eng.brain.write_node(n)
            ids.append(n.id)
        _add_edges(eng.brain,
                   Edge(source=ids[3], target=ids[0], kind="contradicts",
                        pending=False),
                   Edge(source=ids[3], target=ids[1], kind="contradicts",
                        pending=False),
                   Edge(source=ids[3], target=ids[2], kind="supersedes",
                        pending=False))
        data = report_data(eng.brain)
        top = data["intent_queue"][0]
        assert top["source"] == "n3" and top["fan_out"] == 3
        assert top["warn"] is True  # fan-out >= 3 warning
        assert top["kind"] == "mixed"  # contradicts + supersedes from one source
    finally:
        _teardown(eng)


def test_report_excludes_tombstones_and_invalidated():
    eng = _engine()
    try:
        n = Node(id="alive1", text="live node one")
        eng.brain.write_node(n)
        dead = Node(id="deadnode", text="dead node")
        eng.brain.write_node(dead)
        dead.status = "tombstone"
        eng.brain.write_node(dead)
        _add_edges(eng.brain,
                   Edge(source="alive1", target="deadnode", kind="similar",
                        pending=False, valid_to="2026-01-01T00:00:00"))
        data = report_data(eng.brain)
        assert data["nodes"] == 1          # tombstone excluded
        assert data["edges"] == 0          # invalidated edge excluded
    finally:
        _teardown(eng)


def test_report_since_window_semantics():
    eng = _engine()
    try:
        eng.ingest("Die Erde ist eine Scheibe", source="agent/test")
        eng.ingest("Die Erde ist keine Scheibe", source="agent/test")
        # everything is fresh: a 24h window counts both nodes
        data = report_data(eng.brain, since=24)
        assert data["deltas"]["nodes"] == 2
        # an ISO timestamp in the far future counts none
        data = report_data(eng.brain, since="2099-01-01T00:00:00Z")
        assert data["deltas"]["nodes"] == 0
    finally:
        _teardown(eng)


def test_report_structural_section_omitted_without_provider():
    eng = _engine()
    try:
        eng.ingest("alpha beta gamma delta knowledge", source="agent/test")
        out = render_report(eng.brain)
        # no qualifying communities at min_size=15 → section omitted entirely
        assert "## Structural gaps" not in out
    finally:
        _teardown(eng)


def test_report_structural_provider_via_env_json(tmp_path, monkeypatch):
    eng = _engine()
    try:
        eng.ingest("alpha beta gamma delta knowledge", source="agent/test")
        f = tmp_path / "structural.json"
        f.write_text(json.dumps([
            {"kind": "hole", "label": "A <-> B", "node_ids": [],
             "score": 1.0, "hint": "bridge these"}]))
        monkeypatch.setenv("IG_STRUCTURAL_PATH", str(f))
        out = render_report(eng.brain)
        assert "## Structural gaps" in out
        assert "A <-> B" in out
    finally:
        _teardown(eng)
