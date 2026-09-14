# IdeaGraph Live Engine 🕸️

**A self-maintaining, self-improving knowledge graph engine.**

Ingest ideas as Markdown nodes into your own private git repo (the "brain"),
let the engine embed, link, and consolidate them — then steer research with
coverage gaps and grow the engine itself through an eval-gated feedback loop.

![IdeaGraph — demo brain in the web UI](docs/screenshot.png)

## Quickstart

```bash
# 1) set up the engine (Python 3.10+)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 2) create a brain — `--demo` seeds it with an example graph
ig init --demo     # 13 nodes, 19 edges, 2 pending suggestions,
                   # 1 island (ig status), 1 near-dup pair (ig near-dup)

# 3) see it in the web UI
uvicorn ideagraph.server:app --port 8000   # → http://localhost:8000
```

Start from scratch instead with `ig init` (empty brain), connect a private
remote with `ig init --remote <url>`, or auto-clone an existing brain on
first use via `IG_BRAIN_REMOTE=<url>`. Every ingest is a git commit — the
graph grows as visible history.

## How it works

```
┌──────────────┐   git commit+push   ┌────────────────────┐   git pull   ┌─────────────────┐
│ your agent   │ ──────────────────▶ │ your brain repo    │ ◀──────────▶ │ Live Engine     │
│ (CLI/API)    │   (knowledge)       │ (private, Markdown)│  (sync)      │ Ingest→Embed→   │
└──────────────┘                     └────────────────────┘              Suggest→Viz+HITL │
                                                                          └─────────────────┘
```

- **Nodes** — one Markdown file per idea (`nodes/<id>.md`, YAML frontmatter:
  `type: semantic|episodic|procedural`, `status: probation|active|tombstone`)
- **Edges** — `edges.jsonl`, typed (`aehnlich`/similar, `erweitert`/extends,
  `kontradiktorisch`/contradicts, `supersedes`, `continues`, `same_as`),
  bi-temporal (`valid_from`/`valid_to`) with confidence + provenance
- **vectors.jsonl** — embedding cache · **INDEX.md** — generated TOC
- **Human in the loop** — similarity edges ≥ 0.95 auto-accept, the rest go
  pending for review (CLI `ig pending`/`ig accept` or the web UI)

## The self-evolving loop (`tools/`)

The engine doesn't just store knowledge — it improves itself, in three tiers:

1. **Measure** (`ig_cycle`) — safe mechanical ingest runs (marker-scan →
   dry-run → real ingest) record per-run metrics: nodes added, islands,
   duration, acceptance.
2. **Adapt** (`ig_adapt`) — an adaptive controller reads the metrics and
   steers the next runs: research topics with the thinnest coverage get
   higher weight, batch size adapts to timeout history.
3. **Extend** (`ig_evolve`) — brain research becomes engine features via
   red-spec eval cases in the roadmap harness, flipped to the golden set
   only after implementation (first self-extension: `IG_EDGE_CONF_FLOOR`).

## CLI

```bash
ig init [--remote <url>] [--demo]  # create a brain (empty / connected / demo)
ig ingest "New idea ..."           # ingest (duplicates are merged)
ig search "attention"              # hybrid search (dense + BM25 via RRF)
ig pending / accept / reject       # review edge suggestions
ig gaps [--min 10] [--json]        # coverage report + under-covered areas
ig status / near-dup               # hygiene: islands, orphans, near-dup pairs
ig merge <survivor> <deletee>      # consolidate a near-duplicate pair
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `IG_BRAIN_PATH` | `~/ideagraph-brain` | path to the brain clone |
| `IG_BRAIN_REMOTE` | *(none)* | remote brain URL — auto-clones on first use |
| `IG_BRAIN_MODE` | `git` | `local` = filesystem only (tests) |
| `IDEAGRAPH_EMBEDDER` | `st` | `hash` = deterministic test embedder |
| `IDEAGRAPH_AUTO_ACCEPT` | off | `1` = auto-accept all suggested edges |
| `IDEAGRAPH_INTENT_PENDING` | off | `1` = intent edges become pending (HITL) |
| `IDEAGRAPH_RERANKER` | none | optional cross-encoder rerank pass |
| `IG_BOT_NAME` / `IG_BOT_EMAIL` | ideagraph-bot | git commit author |

Dedupe: near-duplicate ingests (cosine ≥ 0.92) merge into the existing node
(`sources:` provenance); opt out with `allow_duplicates: true`.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q   # 120 tests
```

## Status

In development. Core features, hygiene loop, and the self-evolving pipeline
are implemented; release `v0.4.0` is published — see
[CHANGELOG.md](CHANGELOG.md).

## Open source / privacy

The **engine is generic** (this public repo) — the **brain is your private
repo** with your data. The engine contains no brain data.

## License

MIT — see `LICENSE`.
