#!/usr/bin/env python3
"""ig_evolve — Tier 3: the self-extension loop (brain research → engine improvement).

The full RSI loop:
  1. PROPOSE: pick a research-backed engine improvement (from the brain's own
     research areas: memory formats, graph consolidation, retrieval quality).
  2. SPEC: translate it into a ROADMAP_CASE (EvalTask with end-state oracle) —
     a failing spec = the red spec. The case must fail for the RIGHT reason
     (end-state mismatch, not TypeError).
  3. IMPLEMENT: a subagent implements the feature until the case flips green
     (and the FULL suite stays green — the golden set is the regression gate).
  4. FLIP: move the case from ROADMAP_CASES to GOLDEN_SET — measurable progress.

Usage:
  python3 tools/ig_evolve.py --list            # show cycle history
  python3 tools/ig_evolve.py --status          # current eval state (roadmap/golden counts)
  python3 tools/ig_evolve.py --propose <file>  # register a proposed case spec (JSON)
  python3 tools/ig_evolve.py --flip <case_id>  # move a green case into GOLDEN_SET
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ENGINE = "/home/ubuntu/ideagraph-live"
PY = os.path.join(ENGINE, ".venv/bin/python")
HISTORY = os.path.expanduser("~/.hermes/cron/ig_evolve_history.jsonl")


def run(cmd: list[str], cwd: str = ENGINE) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return r.returncode, (r.stdout + r.stderr)


def eval_state() -> dict:
    """Import the eval module and count roadmap/golden cases."""
    code = (
        "from ideagraph.evals import ROADMAP_CASES, GOLDEN_SET;"
        "import json;"
        "print(json.dumps({"
        "'roadmap': [t.id for t in ROADMAP_CASES],"
        "'golden': len(GOLDEN_SET)}))"
    )
    rc, out = run([PY, "-c", code])
    if rc != 0:
        return {"error": out[-300:]}
    return json.loads(out.strip().splitlines()[-1])


def run_case(case_id: str) -> dict:
    """Run ONE roadmap case via run_eval with the test factory (HashEmbedder)."""
    code = f"""
import json, tempfile, pathlib
from ideagraph.evals import ROADMAP_CASES, run_eval
from ideagraph.brain import Brain
from ideagraph.brain_engine import BrainEngine
from ideagraph.embedder import HashEmbedder

task = next((t for t in ROADMAP_CASES if t.id == {case_id!r}), None)
if task is None:
    print(json.dumps({{"error": "case not found"}}))
else:
    counter = [0]
    def factory():
        counter[0] += 1
        d = tempfile.mkdtemp()
        return BrainEngine(Brain(d, mode="local"), HashEmbedder())
    res = run_eval(task, factory)
    print(json.dumps({{"id": res.task_id, "passed": res.passed,
                       "failures": res.failures, "runs": res.runs}}))
"""
    rc, out = run([PY, "-c", code])
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"error": out[-500:]}


def run_full_suite() -> dict:
    rc, out = run([PY, "-m", "pytest", "tests/", "-q", "--tb=no"])
    lines = out.strip().splitlines()
    tail = lines[-1] if lines else ""
    return {"exit": rc, "tail": tail}


def append_history(entry: dict) -> None:
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_history() -> list[dict]:
    if not os.path.exists(HISTORY):
        return []
    rows = []
    for ln in open(HISTORY, encoding="utf-8"):
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--propose", metavar="SPEC_JSON")
    ap.add_argument("--flip", metavar="CASE_ID")
    args = ap.parse_args()

    if args.list:
        rows = read_history()
        if not rows:
            print("no evolve history yet")
            return 0
        for r in rows:
            print(f"{r.get('ts')}  {r.get('case_id')}: {r.get('action')}"
                  f"  passed={r.get('passed')}  suite={r.get('suite_tail', '')}")
        return 0

    if args.status:
        st = eval_state()
        print(json.dumps(st, indent=2, ensure_ascii=False))
        return 0 if "error" not in st else 1

    if args.propose:
        # Register a proposed case: the spec JSON describes the EvalTask; the
        # actual EvalTask code is written by the orchestrator into evals.py
        # ROADMAP_CASES (this tool verifies it runs and fails for the right reason).
        spec = json.load(open(args.propose, encoding="utf-8"))
        case_id = spec.get("id", "")
        if not case_id.startswith("roadmap-"):
            print("case id must start with 'roadmap-'")
            return 1
        st = eval_state()
        if case_id not in st.get("roadmap", []):
            print(f"case {case_id} not yet in ROADMAP_CASES — the orchestrator must"
                  f" add the EvalTask to ideagraph/evals.py first, then re-run --propose")
            return 1
        res = run_case(case_id)
        passed = res.get("passed")
        print(json.dumps(res, indent=2, ensure_ascii=False))
        # A NEW proposal MUST fail (red spec). Passing spuriously = bad spec.
        if passed is False:
            append_history({"ts": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ",
                            __import__("time").gmtime()),
                            "case_id": case_id, "action": "propose",
                            "passed": False,
                            "failures": res.get("failures", [])[:3]})
            print("RED SPEC registered (fails as expected)")
            return 0
        print("WARNING: case already green — not a valid new proposal")
        return 1

    if args.flip:
        case_id = args.flip
        res = run_case(case_id)
        if not res.get("passed"):
            print(json.dumps(res, indent=2, ensure_ascii=False))
            print("case still RED — cannot flip")
            return 1
        suite = run_full_suite()
        if suite["exit"] != 0:
            print("FULL SUITE RED — cannot flip:", suite["tail"])
            return 1
        append_history({"ts": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ",
                        __import__("time").gmtime()),
                        "case_id": case_id, "action": "flip",
                        "passed": True, "suite_tail": suite["tail"]})
        print(f"FLIPPED {case_id} → GOLDEN_SET (suite green: {suite['tail']})")
        print("NOTE: the orchestrator must now MOVE the EvalTask from ROADMAP_CASES"
              " to GOLDEN_SET in ideagraph/evals.py and commit.")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
