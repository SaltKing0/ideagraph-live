#!/usr/bin/env python3
"""ig_cycle — the mechanical research-ingest cycle for the IdeaGraph brain.

Runs the full SAFE ingest pipeline for a batch of subagent-produced findings:
  collect (glob /tmp/dogfood_*.txt, dedup) → marker-scan (fail on intent markers)
  → dry-run on a copy → real ingest (git, INTENT_PENDING=1) → accept edges
  → report node count + islands.

The RESEARCH part (spawning subagents to write the findings) is done by the
orchestrator (agent / cron) around this script. This script is the reproducible,
safety-checked mechanical core. It NEVER ingests blind: a marker hit or a failed
dry-run aborts before anything touches the real brain.

Usage:
  python3 tools/ig_cycle.py [--glob '/tmp/dogfood_*.txt'] [--brain /home/ubuntu/ideagraph-brain]
                            [--engine /home/ubuntu/ideagraph-live] [--dry-run-only]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

DEFAULT_METRICS = os.path.expanduser("~/.hermes/cron/ig_metrics.jsonl")

# Intent-marker substrings (exact) that must NOT appear in a finding.
MARKERS = [
    "ersetzt", "statt", "anstelle", "keine", "kein", "nicht", "sondern",
    "falsch", "basiert auf", "aufbauend", "weiterentwickelt", "verfeinert",
    "erweitert um", "uebersetzt", "ersetzbar", "verfeinerung",
]
# Allowlisted innocent substrings that CONTAIN a marker (false positives).
ALLOW = ["stattet", "stätte", "Nichtabstreitbarkeit", "Unabstreitbarkeit"]


def collect(files: list[str]) -> list[tuple[str, str]]:
    seen = set()
    out: list[tuple[str, str]] = []
    for f in sorted(files):
        for ln in open(f, encoding="utf-8"):
            ln = ln.rstrip("\n")
            if not ln.strip():
                continue
            if "\t" in ln:
                src, finding = ln.split("\t", 1)
            else:
                src, finding = "dogfood/gap?", ln
            if finding in seen:
                continue
            seen.add(finding)
            out.append((src, finding))
    return out


def marker_scan(findings: list[tuple[str, str]]) -> list[str]:
    bad = []
    for src, finding in findings:
        low = finding.lower()
        for m in MARKERS:
            if m in low and not any(a in low for a in ALLOW):
                bad.append(f"{src}: enthaelt Marker '{m}'")
    return bad


def run(cmd: list[str], env: dict, cwd: str) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed ({r.returncode}): {' '.join(cmd)}\n{r.stderr[-800:]}")
    return r.stdout + r.stderr


def write_metrics(entry: dict, path: str = DEFAULT_METRICS) -> None:
    """Append one JSON line to the metrics log (Tier 1: self-measurement)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"metrics write failed (non-fatal): {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="/tmp/dogfood_*.txt")
    ap.add_argument("--brain", default="/home/ubuntu/ideagraph-brain")
    ap.add_argument("--engine", default="/home/ubuntu/ideagraph-live")
    ap.add_argument("--dry-run-only", action="store_true")
    ap.add_argument("--copy", default="/tmp/ig-brain-dryrun")
    args = ap.parse_args()

    t0 = time.time()
    n_before = len([f for f in os.listdir(os.path.join(args.brain, "nodes"))
                    if f.endswith(".md")])
    # Engine venv python (has numpy/st embedder); fall back to current interpreter.
    eng_py = os.path.join(args.engine, ".venv", "bin", "python")
    if not os.path.exists(eng_py):
        eng_py = sys.executable
    files = sorted(glob.glob(args.glob))
    if not files:
        print("NO findings files matched", args.glob)
        return 1
    findings = collect(files)
    if not findings:
        print("no findings after dedup")
        return 1
    print(f"collect: {len(files)} files -> {len(findings)} findings")

    bad = marker_scan(findings)
    if bad:
        print("MARKER FAIL (abort, nothing ingested):")
        for b in bad:
            print("  -", b)
        write_metrics({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "aborted": "marker", "marker_fails": len(bad),
                       "marker_words": sorted({m for _, f in findings for m in MARKERS
                                               if m in f.lower()
                                               and not any(a in f.lower() for a in ALLOW)}),
                       "findings": len(findings)})
        return 1
    print("marker-scan: CLEAN")

    # Dry-run on a copy (exclude .git, per skill).
    if os.path.exists(args.copy):
        shutil.rmtree(args.copy)
    os.makedirs(args.copy)
    shutil.copytree(os.path.join(args.brain, "nodes"), os.path.join(args.copy, "nodes"))
    for f in ("edges.jsonl", "vectors.jsonl", "INDEX.md"):
        shutil.copy(os.path.join(args.brain, f), os.path.join(args.copy, f))
    dry_env = dict(os.environ, IG_BRAIN_PATH=args.copy, IG_BRAIN_MODE="local",
                   IDEAGRAPH_INTENT_PENDING="1", IDEAGRAPH_EMBEDDER="st")
    dry_islands = []
    for src, finding in findings:
        out = run([eng_py, "-m", "ideagraph", "ingest", finding, "--source", src],
                  dry_env, args.engine)
        n = out.count("Vorschlag:")
        m = __import__("re").search(r"Node (\w{12}):", out)
        if m and n == 0:
            dry_islands.append(m.group(1))
    print(f"dry-run: {len(findings)} findings on copy, islands={dry_islands}")
    if args.dry_run_only:
        print("dry-run-only: stopping (brain untouched)")
        return 0

    # Real ingest (git, INTENT_PENDING safety net).
    git_env = dict(os.environ, IG_BRAIN_MODE="git", IDEAGRAPH_INTENT_PENDING="1",
                   IDEAGRAPH_EMBEDDER="st")
    real_islands = []
    for src, finding in findings:
        out = run([eng_py, "-m", "ideagraph", "ingest", finding, "--source", src],
                  git_env, args.engine)
        n = out.count("Vorschlag:")
        m = __import__("re").search(r"Node (\w{12}):", out)
        if m and n == 0:
            real_islands.append(m.group(1))
    print(f"ingest: {len(findings)} findings, 0-edge islands={real_islands}")

    # Accept pending edges (one commit).
    review = os.path.join(os.path.dirname(__file__), "..", "..",
                          ".hermes", "skills", "software-development",
                          "ideagraph-engine", "scripts", "review_edges.py")
    review = os.path.abspath(review)
    out = run([eng_py, review], git_env, args.engine)
    print(out.strip().splitlines()[-1] if out.strip() else "review: no output")

    # Report node count + write Tier-1 metrics.
    n_nodes = len([f for f in os.listdir(os.path.join(args.brain, "nodes"))
                   if f.endswith(".md")])
    print(f"nodes now: {n_nodes}")
    print(f"ISLANDS_TO_FIX: {real_islands}")
    write_metrics({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "nodes_before": n_before, "nodes_after": n_nodes,
                   "nodes_added": n_nodes - n_before,
                   "findings": len(findings),
                   "islands_found": len(real_islands),
                   "duration_s": round(time.time() - t0, 1),
                   "timed_out": False})
    return 0


if __name__ == "__main__":
    sys.exit(main())
