# Changelog

All notable changes to this project. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project
follows [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`ig accept-pending`** — the review policy as a command: accepts pending
  suggestions in ONE commit, but caps auto-accepted intent edges per source
  (`--max-intent-per-source`, default 2, env `IG_INTENT_AUTO_ACCEPT_MAX`).
  Everything beyond the cap stays pending for `ig pending`; `--dry-run` shows
  the decision without writing, `--json` is machine-readable.
- **Intent fan-out dam** (`ideagraph/review.py`, enforced in
  `brain_engine.ingest` at birth and on the review path): at most 2 intent
  edges (`contradicts`/`supersedes`/`continues`) per source are auto-accepted,
  the rest are born pending — kept and reviewable instead of invisible.
  Eval layer: `EvalOracle.max_auto_intent_per_source` + the ROADMAP_CASE
  `roadmap-intent-fanout-cap`, registered RED, implemented, flipped (22 golden
  cases).
- `tools/ig_cycle.py` now runs the engine's review policy (`ig accept-pending`)
  instead of the external accept-ALL script — the previous default path is
  exactly the leak the cap closes. `IG_REVIEW_SCRIPT` remains an explicit
  opt-in override (no default path: an unset variable must not silently bypass
  the cap). `ig report`'s intent queue now shows how many edges per source are
  HELD (`N pending`), so the section is a review queue instead of a report of
  past damage.

### Fixed
- **Unreviewed intent-edge stream.** Intent edges carry `confidence=None`, so
  the 0.95 auto-accept band could never judge them, while the marker heuristic
  auto-accepted every edge it produced. Measured on the live brain before the
  dam: 168 intent edges ever created, **66 of them invalidated again (39 %
  false)**, one source holding 10 auto-accepted `contradicts`, and 26 false
  edges added in a single cycle — none of them visible in `ig pending`. The cap
  is a bound, not a repair: marker heuristics cannot read descriptive negation,
  so the semantic fix stays a documented roadmap item.

## [0.5.4] - 2026-09-18

### Changed
- `fastapi` pin `0.116.0` → `0.141.1`. The old pin forced `starlette<0.47`, which made
  the `mcp` extra uninstallable on Python 3.14 (see Fixed). The server code needs no
  changes: the full suite is green on both `starlette 0.46.2` and `starlette 1.6.0`, and a
  live uvicorn smoke (UI, `/api/graph`, `/api/report`, `/report`) works on the new pair.

### Fixed
- **`pip install 'ideagraph-live[mcp]'` is resolvable again on Python 3.14.** It failed
  with `ResolutionImpossible`: `fastapi==0.116.0` pinned `starlette>=0.40,<0.47`, while
  `mcp>=1.28` declares `starlette>=0.48.0; python_version >= "3.14"`. A fresh 3.14 install
  now resolves `fastapi 0.141.1 + starlette 1.6.0 + mcp 1.30.0 + sse-starlette 2.4.1`
  (verified with `pip install --dry-run` and a real install, plus a stdio MCP smoke).
  The base install was never affected — only the documented MCP extra was.

## [0.5.3] - 2026-09-18

### Added
- **Read-only MCP server** (`ig mcp` / `ig-mcp`, new `mcp` extra): exposes the
  brain to AI assistants over stdio with four `readOnlyHint` tools —
  `search_brain` (hybrid search; scores are rank-fusion, not similarity),
  `get_node` (full text capped + live edges), `neighbors` (undirected 1-2-hop
  graph neighborhood via the new `ideagraph.graph` seam), and `brain_status`
  (size/connectivity/pending load, basename-only path). No write tools by
  design; the engine loads lazily; payloads are capped and escaped in one
  place (`ideagraph/mcp/format.py`); the vector cache is never written by
  default (`IG_MCP_CACHE_VECTORS=1` opts in) so a cold-clone search cannot
  dirty the private repo. Cold-search cost measured on a 1821-node clone
  (2-core VPS, all-MiniLM-L6-v2): 275 s one-time embed — memoized in-process,
  so subsequent searches in the same server session are warm (~2 s); with
  `persist=True` the fill lands on disk once (352 s incl. write) and warm
  searches stay ~2 s. Opt-in assistant prompt snippet shipped at
  `ideagraph/mcp/agent/instructions.md`.
- Engine seams: `Brain.read_node(id)` (single-node fetch without the full
  glob), `vectors_for(..., persist=False)` (compute without writing the cache;
  threaded through `retrieve()`), `ideagraph/graph.py` (undirected live-edge
  neighborhood, shared primitive from report #1).
- Eval layer: `NeighborhoodExpectation` + `verify_neighborhood` (graceful
  degrade when `graph.py` is absent); golden case `roadmap-neighbors` flipped
  (21 golden cases).
- `ig communities` — read-only topology report: deterministic label-propagation
  communities (canonical 0..k-1), god nodes (degree AND normalized Brandes
  betweenness — the rankings diverge substantially), and structural gaps ranked
  by deficit against the configuration-model null (`expected = comdeg_a *
  comdeg_b / 2m`). `--min-size`, `--top`, `--no-pending`, `--betweenness-sample`,
  `--members`, `--json`. No new dependencies (networkx is deliberately not used —
  undeclared and absent in CI); nothing is written to the brain.
- Eval layer: `CommunityExpectation` (asserts `together` AND `apart` AND `gap`)
  + `verify_communities` wired into `run_eval`; golden case
  `roadmap-communities-two-clusters` registered RED, implemented, flipped
  (19 golden cases).
- `ig report` / `GET /api/report` + `/report` web page — one-page read-only
  BRAIN_REPORT digest (report #7): deltas since a window, edge mix + confidence
  bands, intent review queue grouped by source fan-out (the measured
  false-positive signature), hubs + degree percentiles, hygiene, research next.
  `--since` (hours or ISO), `--top`, `--json`, `--coverage` (opt-in, measured
  5.8 s), `--write` regenerates the tracked `BRAIN_REPORT.md` at the brain root
  (one commit per generation; the cron cycle calls it automatically). The
  structural-gaps section consumes `ig communities` via a provider seam and is
  omitted — never printed empty — when no community qualifies. Escaping order
  is truncate-then-escape (audit #55); an empty body hard-fails instead of
  writing a blank artifact. Golden case `roadmap-brain-report` registered RED,
  implemented, flipped (20 golden cases).

### Fixed
- `tools/ig_evolve.py --flip` deadlock: audit #52's flip-gate test forces a green
  roadmap case out of `ROADMAP_CASES` BEFORE the suite can go green, but `--flip`
  only looked in `ROADMAP_CASES` — it now falls back to `GOLDEN_SET`, so the
  documented flip procedure works again.
- Test-fixture lesson: LPA's update order is sorted(node ids) — uuid4 fixture ids
  shuffled that order between runs and flaked borderline partitions. Fixtures now
  pin ids (the live brain has stable ids, so production determinism is unaffected).
- `ig near-dup` reviewed tombstones: `ig merge` tombstones the deletee and
  redirects its edges, but the deletee's vector stays in `vectors.jsonl`, so the
  pair it was merged for re-appeared in EVERY later report and could never be
  cleared. `near_dup_pairs()` now filters `status != "tombstone"` before the
  cosine matrix — the same live-node rule already applied in `connectivity()`
  and `analyze_coverage()`.

## [0.5.2] - 2026-09-15

### Added
- `ig search --json` — machine-readable hybrid search; stdout carries ONLY the
  JSON payload, so `ig search "..." --json | jq` works on any install.

### Fixed
- **The sentence-transformers fallback notice goes to stderr, not stdout** —
  the notice corrupted piped JSON output (`ig search --json | jq`) and would
  have corrupted a stdio MCP server's JSON-RPC transport.

### Changed
- `ideagraph/runtime.py` — one shared brain/engine factory for the CLI and
  the FastAPI server (previously two drifting copies; the server keeps its
  process-wide engine cache, now in one place).

## [0.5.1] - 2026-09-15

### Added
- **PyPI publishing** via GitHub Actions with OIDC trusted publishing
  (`.github/workflows/release.yml`) — publishing a release uploads to PyPI,
  no token in the repo.
- **Dedicated CI job for the real embedder** (`test-st`) — installs the `[st]`
  extra (CPU torch) so the embedder-dependent tests run for real; the light
  job covers the default install path.
- `[project.urls]` in `pyproject.toml` — repository and issue links on PyPI.

### Fixed
- **CI green again on the default install** — `tests/test_cli.py`,
  `tests/test_tools.py` and `tests/test_frontend_xss.py` hardcoded the repo's
  `.venv/bin/python` (absent in CI) and now use `sys.executable`; tests that
  need sentence-transformers skip instead of failing when the extra is absent.
- `ig status` / `ig gaps` ignore tombstoned nodes — a merged-away node no
  longer shows up as a permanent phantom orphan/island.
- `tools/ig_cycle.py` expands `~` in its `--brain` default (the documented
  no-argument cron invocation aborted on a literal `~/...` path).
- **`ig init --remote <existing brain>` clones instead of forking it** — on a
  machine without a clone it created a second, unrelated root commit, so the
  next push was rejected as a non-fast-forward and the brain looked broken.
- **Pipeline tools run without a repo venv** — `ig_evolve.py` aborted with
  "engine venv python not found" and `ig_adapt.py` silently returned no gap
  weights when `<engine>/.venv` was missing (CI, plain `pip install`). Both now
  fall back to the running interpreter, like `ig_cycle.py` already did.
- **`ig_evolve --list` reads an overridable history path** —
  `IG_EVOLVE_HISTORY` replaces the hardcoded
  `~/.cache/ideagraph/ig_evolve_history.jsonl`, and the test seeds its own file
  instead of asserting on whatever the machine happens to have (it passed
  locally, where the file existed, and failed in CI).
- **Installable on current Pythons** — `numpy==2.3.1` ships wheels for
  cp311–cp313 only, so `pip install ideagraph-live` failed to resolve on
  Python 3.14 (and on 3.10). The pin now carries an environment marker
  (`>=2.3.2` on 3.14+) and `requires-python` is `>=3.11`.
- **`tools/ig_cycle.py` respects the caller's embedder** — the cycle hardcoded
  `IDEAGRAPH_EMBEDDER=st` for its ingest subprocesses, so a caller that asked
  for the hash embedder still triggered a model download (and the pipeline
  tests were network-dependent/flaky). The real embedder stays the default.

### Changed
- Repository hygiene: build artifacts (`*.egg-info/`) are no longer tracked,
  `CONTRIBUTING.md` reflects the current suite and tooling, and the older
  changelog entries are in English like the rest of the repo.

## [0.5.0] - 2026-09-14

### Changed
- **BREAKING: canonical English edge kinds** — `ähnlich`→`similar`,
  `erweitert`→`extends`, `kontradiktorisch`→`contradicts` everywhere (data
  model, suggester/intent emission, evolution, merge directionality, demo
  seed, fixtures, UI). Existing brains migrate with
  `python tools/migrate_kinds.py [--apply]` (dry-run default, atomic write,
  backup, idempotent).
- Intent text markers ("erweitert um", "ersetzt", …) stay bilingual — they
  match user prose, not the data format.

### Fixed
- Eval oracle matching: exact-match-beats-prefix node resolution, `no_edge`
  oracle respects `valid_to`/`kind`, flip verification runs pass³ (#27).
- Server: empty-text ingest returns a clean 400 instead of a 500 (#57).

### Performance
- Batch embedding (`embed_batch`) — cold vector cache embeds in ONE model
  call instead of one call per node (#60).
- Hygiene reports cache parsed vectors (mtime-keyed) (#60).

### Added
- **pip-installable end to end** — the web UI ships inside the package
  (`ideagraph/web/`), so `pip install` serves the full cockpit; core
  dependencies are lightweight and the sentence-transformers embedder is
  now the optional `[st]` extra (falls back to the deterministic
  HashEmbedder with a notice when absent).
- README documents installing straight from the repository.
- `IDEAGRAPH_EMBEDDER_MODEL` / `get_embedder(name, model)` — embedder model
  override (#60).
- `ig_cycle --metrics` — route metrics output for tests/side-runs (#57).
- Test coverage: CLI dispatch (15), pipeline tools (8), git mode +
  crash-safety (5), server error paths (7), browser-level XSS regression
  via Playwright (2) (#57).

## [0.4.0] - 2026-09-14

### Added
- **Demo seed brain (`ig init --demo`)** — a pre-filled example graph for
  onboarding: 13 generic nodes, 19 edges covering every edge type, 2 pending
  suggestions for the HITL flow, one island (`ig status`), one measured
  near-dup pair (`ig near-dup`/`ig merge`), precomputed vectors (`ig search`
  works immediately).
- **English UI** — the web cockpit (capture bar, graph, legend, review
  inbox, review page) is now fully English, matching the OSS scope; edge
  kind values on disk stay unchanged.
- **README hero screenshot** — the demo brain rendered in the web UI.
- **`ig status` — connectivity/hygiene report.** Reports node/edge counts,
  degree stats, orphans (0 edges), islands (≤1), weak (==2), and the status
  distribution (probation backlog). Read-only; `--json` for machine-readable.
- **`ig near-dup` — near-duplicate detection.** Flags node pairs in the cosine
  band [0.78, 0.92) — the near-duplicates below the auto-dedup threshold (0.92)
  that need a manual `ig merge` decision. Read-only; `--lo/--hi/--max/--json`.
  Complements `ig merge` by driving it with a report instead of manual digging.
- **`ig merge <survivor> <deletee>` — near-duplicate consolidation.** Manually
  consolidates two closely-related nodes into one: all edges of the deletee are
  redirected to the survivor (deduped, self-loops dropped), the text is appended
  for information preservation, and the deletee's node file + vector are removed.
  `INDEX.md` is rebuilt and everything lands in a single commit. This is the
  manual complement to the automatic ingest dedup (cos ≥ 0.92): near-duplicates
  in the ~0.78–0.92 band stay under the auto threshold and need this.
- **`ig gaps` — coverage & gap analysis.** Classifies every node against a
  topic taxonomy (area → keywords), reports coverage per area with a visual
  bar, and flags under-covered areas as gaps to steer research. Read-only;
  taxonomy is configurable via `--taxonomy tax.json`, threshold via `--min N`,
  machine-readable output via `--json`. Ships a sensible default LLM/agent
  taxonomy (`ideagraph.gaps.DEFAULT_TAXONOMY`).
- **3D Graph UI** — the cockpit's Graph tab now renders the idea network as a
  3D force-directed graph (Three.js / WebGL via `3d-force-graph`): drag to
  rotate, scroll to zoom, hover tooltip, click for node details, search to
  center. Node size scales with degree (hubs stand out), edge color encodes
  edge kind, pending edges are dimmed, and non-pending edges show a subtle
  directional particle flow. Automatically falls back to the classic 2D d3
  force graph when WebGL is unavailable.
- **Demo seed brain (`ig init --demo`)** — a pre-filled example graph for
  onboarding: 13 generic nodes (RAG, retrieval, memory, hygiene), 19 edges
  covering every edge type, 2 pending suggestions for the HITL review flow,
  1 island node to demo `ig status`, 1 near-dup pair to demo
  `ig near-dup` + `ig merge`, and a DE/EN `same_as` pair. Precomputed
  vectors make `ig search` work immediately.
- **Self-evolving pipeline tools (`tools/`)** — a three-tier feedback loop that
  turns the engine into a self-improving system:
  - `tools/ig_cycle.py` (Tier 1) — the safe mechanical ingest pipeline
    (collect → marker-scan abort → dry-run on a copy → real ingest → accept
    edges → report). Never ingests blind; appends one JSON metrics line per run
    (nodes added, islands, duration, timeouts) to
    `~/.cache/ideagraph/ig_metrics.jsonl`.
  - `tools/ig_adapt.py` (Tier 2) — the adaptive controller: reads the metrics,
    writes `cycle_strategy.json` with topic weights (thin areas boosted, focus
    areas weighted 2x), quality-driven findings rules, and an adaptive batch
    size (timeouts shrink it, healthy runs grow it back).
  - `tools/ig_evolve.py` (Tier 3) — the self-extension harness: turns
    brain-researched improvements into engine features via the eval harness
    (`--propose` registers a RED spec, `--flip` verifies case + full suite
    green and records the ROADMAP→GOLDEN promotion in a history log).
- **Confidence floor for auto-edges** — `ingest(..., env={"IG_EDGE_CONF_FLOOR": ...})`
  (or the env var) drops similarity-edge suggestions below the floor instead of
  leaving them pending; default `0.0` = no behavior change. Protects autonomous
  ingest loops from low-confidence edge floods. Proven via the first
  self-extension cycle (red spec → implemented → flipped to the golden set).

### Changed
- `BrainEngine.ingest()` accepts an optional `env` dict for per-call
  environment overrides (used by eval tasks and the confidence floor).

## [0.3.1] - 2026-08-31

### Added
- **`ig init` onboarding** — create a new brain repo with one command (git repo
  + `nodes/`, `edges.jsonl`, `vectors.jsonl`, `INDEX.md` + first commit). Optional
  `--remote <url>` connects and pushes an existing private brain remote.
- **Auto-init on first use** — `ig ingest` (and `ig link`/`ig accept`) on a fresh
  machine now creates the brain repo automatically instead of failing; `pull`/
  `push` are no-ops when no remote is configured.

### Changed
- `Brain.init()` / `Brain.ensure_ready()` — idempotent brain bootstrap.
- `commit_and_push(push=...)` — skips push when no `origin` exists.

## [0.3.0] - 2026-08-27

### Added
- **Cross-encoder rerank pass (V2#1)** — optional second retrieval stage:
  hybrid retrieval returns top-K candidates, an optional cross-encoder
  reranks them onto the final top-k. No new hard dependency; enabled via
  `IDEAGRAPH_RERANKER` (`st` = sentence-transformers CrossEncoder, or a
  model name/path). Backward compatible (off by default).
- **Admit-rule enforcement (V2#3)** — opt-in governance: with
  `consolidate(admit_required=True)`, a node without relations stays in
  `probation` instead of being promoted. Default unchanged (promote all).

### Changed
- `retrieve()` supports a pluggable reranker (`engine.reranker`);
  `EvalTask` gained an optional `reranker` for retrieval evals.
- `consolidate()` accepts `admit_required` (opt-in Admit-Rule).

### Known limitations
- **Marker-based intent detection** (`supersedes`/`kontradiktorisch`/
  `continues`) can fire false edges on real prose: a neutral word such as
  "kein"/"nicht"/"statt" against a thematically related node can trigger a
  wrong intent edge. The `IDEAGRAPH_INTENT_PENDING=1` safety net keeps any
  such edges pending (reviewable) instead of auto-accepted.

## [0.2.0] - 2026-08-23

### Added
- **Tab cockpit UI** (`ideagraph/web/index.html` + `app.js`): three tabs —
  **Ingest** (start page), **Graph**, **Review** — replacing the previous
  single-screen layout.
- **Graph interaction (Obsidian-like):** wheel zoom, pan by dragging the
  background, hover tooltip, click for node details, double-click focus
  (highlight neighbours, dim the rest), node search with center/zoom,
  zoom buttons.
- **`IDEAGRAPH_INTENT_PENDING` config option:** intent edges (supersedes /
  continues / contradicts) can optionally go to `pending` (HITL review)
  instead of being auto-accepted.
- **Packaging:** `pyproject.toml` — pip-installable, `ig` console script,
  `requires-python >= 3.10`, dependencies, `[project.optional-dependencies] dev`.
- **CI:** GitHub Actions workflow (`.github/workflows/ci.yml`) — pytest on
  push/PR for Python 3.11 and 3.12.
- **`CONTRIBUTING.md`** — contribution guide.
- **`CHANGELOG.md`** (and a `CODE_OF_CONDUCT.md`, dropped again before 0.5.0 —
  no public enforcement contact was wanted).
- **README screenshot** of the Graph tab.

### Changed
- **Intent detection hardened:** `detect_intent` now requires shared content
  words (stopword filter) for every intent including `supersedes`; and intent
  edges only appear at a real ST cosine >= 0.45 (the same threshold as
  `extends`). A marker word in the text can no longer mark a node as an intent
  against EVERY existing node.
- **README** substantially revised (tab UI, V2 features, OSS/privacy, env table).
- **Engine decoupled from the brain:** no hardcoded private remote or bot
  identity any more; everything is configurable via env (`IG_BRAIN_REMOTE`,
  `IG_BOT_NAME`, `IG_BOT_EMAIL`).
- **No-cache headers** on static UI routes (fixes "tab bar not clickable" caused
  by a cached old JS bundle).

### Fixed
- Intent edges fired on marker words ("supersedes", "ersetzt", "statt") against
  almost every node — now bounded by the similarity gate.
- A cached old `app.js` (referencing removed elements) crashed the JS, so the
  tabs looked dead; solved with cache busting + no-store.

## [0.1.1] - 2026-08-22

### Added
- Web UI cockpit (`/` + `/review`), FastAPI server, WebSocket live updates.
- CLI: `ingest`, `pending`, `accept`, `reject`, `link`, `search`.

## [0.1.0] - 2026-08-22

### Added
- Brain layer as a private git repo (nodes as Markdown, edges as JSONL,
  embedding cache, INDEX.md).
- Embedder: sentence-transformers (all-MiniLM-L6-v2) + a deterministic
  HashEmbedder for tests.
- Dedupe (cosine >= 0.92 → merge instead of creating a new node).

## [0.0.1] - 2026-08-21

### Added
- First runnable skeleton: ingest → embed → suggest approach, README, MIT
  license. Similarity edges (`ähnlich`, `erweitert` — renamed to
  `similar`/`extends` in 0.5.0).

[Unreleased]: https://github.com/SaltKing0/ideagraph-live/compare/v0.5.4...HEAD
[0.5.4]: https://github.com/SaltKing0/ideagraph-live/compare/v0.5.3...v0.5.4
[0.5.3]: https://github.com/SaltKing0/ideagraph-live/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/SaltKing0/ideagraph-live/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/SaltKing0/ideagraph-live/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/SaltKing0/ideagraph-live/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/SaltKing0/ideagraph-live/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/SaltKing0/ideagraph-live/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/SaltKing0/ideagraph-live/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/SaltKing0/ideagraph-live/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/SaltKing0/ideagraph-live/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/SaltKing0/ideagraph-live/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/SaltKing0/ideagraph-live/releases/tag/v0.0.1
