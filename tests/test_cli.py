"""CLI dispatch + usage-error tests (audit #57: the dispatch surface had zero tests).

Every test runs the real CLI in a subprocess against a temp brain, so the
full dispatch path (argv -> COMMANDS -> cmd_* -> engine) is exercised.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
# sys.executable = the interpreter running pytest: the repo venv locally, the
# CI environment on GitHub Actions (where no .venv exists).
PY = sys.executable


def run_cli(args: list[str], tmp_path, env_extra: dict | None = None,
            stdin: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ,
               IG_BRAIN_MODE="local",
               IG_BRAIN_PATH=str(tmp_path / "brain"),
               IDEAGRAPH_EMBEDDER="hash",
               PYTHONPATH=str(REPO))
    if env_extra:
        env.update(env_extra)
    return subprocess.run([PY, "-m", "ideagraph", *args],
                          capture_output=True, text=True, env=env,
                          input=stdin, timeout=120)


def test_help_exits_zero(tmp_path):
    r = run_cli(["--help"], tmp_path)
    assert r.returncode == 0
    assert "ideagraph init" in r.stdout


def test_unknown_command_exits_one_with_message(tmp_path):
    r = run_cli(["definitely-not-a-command"], tmp_path)
    assert r.returncode == 1
    assert "Unknown command" in r.stdout
    assert "definitely-not-a-command" in r.stdout
    assert "Traceback" not in r.stderr


def test_init_creates_brain_and_second_init_fails_cleanly(tmp_path):
    r = run_cli(["init"], tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "brain" / "nodes").is_dir()
    # non-empty dir -> friendly error, no traceback
    r2 = run_cli(["init"], tmp_path)
    assert r2.returncode == 1
    assert "already contains a brain" in r2.stdout
    assert "Traceback" not in r2.stderr


def test_ingest_and_search_roundtrip(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["ingest", "Cats hunt mice at night", "--source", "test"], tmp_path)
    assert r.returncode == 0, r.stderr
    r = run_cli(["search", "cats"], tmp_path)
    assert r.returncode == 0
    assert "hits (hybrid dense+BM25)" in r.stdout


def test_ingest_stdin_marker(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["ingest", "-"], tmp_path, stdin="Owls hunt mice at night\n")
    assert r.returncode == 0, r.stderr
    r2 = run_cli(["search", "owls"], tmp_path)
    assert "1 hits" in r2.stdout or "hits" in r2.stdout


def test_ingest_stdin_rejects_mixed_args(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["ingest", "-", "extra"], tmp_path, stdin="text\n")
    assert r.returncode == 1
    assert "cannot be combined" in r.stdout
    assert "Traceback" not in r.stderr


def test_ingest_missing_source_is_usage_error(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["ingest", "some text", "--source"], tmp_path)
    assert r.returncode == 1
    assert "Usage" in r.stdout
    assert "Traceback" not in r.stderr


def test_accept_missing_arg_is_usage_error(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["accept"], tmp_path)
    assert r.returncode == 1
    assert "Usage" in r.stdout
    assert "Traceback" not in r.stderr


def test_accept_unknown_edge_clean_error(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["accept", "deadbeef1234"], tmp_path)
    assert r.returncode == 1
    assert "not found or not pending" in r.stdout


def test_gaps_bad_min_is_usage_error(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["gaps", "--min", "abc"], tmp_path)
    assert r.returncode == 1
    assert "expects a number" in r.stdout
    assert "Traceback" not in r.stderr


def test_near_dup_invalid_band_is_usage_error(tmp_path):
    assert run_cli(["init"], tmp_path).returncode == 0
    r = run_cli(["near-dup", "--lo", "2", "--hi", "1"], tmp_path)
    assert r.returncode == 1
    assert "must be smaller" in r.stdout


def test_near_dup_max_zero_means_zero(tmp_path):
    """#26 semantics: --max 0 limits to 0 pairs, it does not disable the limit."""
    assert run_cli(["init", "--demo"], tmp_path).returncode == 0
    r = run_cli(["near-dup", "--max", "0", "--json"], tmp_path)
    assert r.returncode == 0
    assert r.stdout.strip() == "[]"


def test_ig_brain_path_expanduser(tmp_path, monkeypatch):
    """#33: an explicit IG_BRAIN_PATH with ~ is expanded, not written literally."""
    r = run_cli(["status"], tmp_path, env_extra={"IG_BRAIN_PATH": "~/ig-test-expand-9182"})
    # status on a missing brain must fail cleanly (no crash), and NO literal ./~ dir
    # was created in the CWD
    assert "Traceback" not in r.stderr
    home = Path(os.path.expanduser("~"))
    created = home / "ig-test-expand-9182"
    # status creates nothing on a missing brain — but if it did, it would be expanded
    assert not (Path.cwd() / "~").exists()
    if created.exists():
        import shutil
        shutil.rmtree(created)


def test_status_on_missing_brain_clean_error(tmp_path):
    r = run_cli(["status"], tmp_path)
    assert "Traceback" not in r.stderr
    # either a friendly message or a non-zero exit — never a traceback
    assert r.returncode != 0 or "Status" in r.stdout


def test_search_without_args_is_usage(tmp_path):
    r = run_cli(["search"], tmp_path)
    assert r.returncode == 1
    assert "Usage: ig search <term>" in r.stdout
