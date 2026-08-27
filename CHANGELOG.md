# Changelog

All notable changes to this project. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project
follows [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- _(nothing planned yet)_

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
- **Tab-Cockpit-UI** (`docs/index.html` + `docs/app.js`): drei Tabs —
  **Ingest** (Startseite), **Graph**, **Review** — statt des bisherigen
  Ein-Screen-Layouts.
- **Graph-Interaktion (Obsidian-artig):** Mausrad-Zoom, Pan per Ziehen auf
  dem Hintergrund, Hover-Tooltip, Klick auf Node-Details, Doppelklick-Fokus
  (Nachbarn hervorheben, Rest abdimmen), Node-Suche mit Zentrieren/Zoomen,
  Zoom-Buttons.
- **Config-Option `IDEAGRAPH_INTENT_PENDING`:** Intent-Edges (supersedes /
  continues / kontradiktorisch) können optional auf `pending` (HITL-Review)
  statt auto-akzeptiert umgestellt werden.
- **Packaging:** `pyproject.toml` — pip-installierbar, `ig`-Console-Script,
  `requires-python >= 3.10`, Dependencies, `[project.optional-dependencies] dev`.
- **CI:** GitHub Actions-Workflow (`.github/workflows/ci.yml`) — pytest auf
  Push/PR für Python 3.11 und 3.12.
- **`CONTRIBUTING.md`** — Beitragsleitfaden.
- **`CHANGELOG.md`** und **`CODE_OF_CONDUCT.md`**.
- **README-Screenshot** des Graph-Tabs.

### Changed
- **Intent-Erkennung gehärtet:** `detect_intent` verlangt jetzt geteilte
  Inhaltswörter (Stoppwort-Filter) für alle Intents inkl. `supersedes`; und
  Intent-Edges entstehen nur noch bei echtem ST-Kosinus ≥ 0.45 (Schwelle
  wie `erweitert`). Ein Marker-Wort im Text kann eine Node nicht mehr gegen
  JEDE bestehende Node als Intent markieren.
- **README** umfassend überarbeitet (Tab-UI, V2-Features, OSS/Privatsphäre,
  Env-Tabelle).
- **Engine vom Brain entkoppelt:** kein hardcoded privater Remote /
  Bot-Identität mehr; alles per Env konfigurierbar (`IG_BRAIN_REMOTE`,
  `IG_BOT_NAME`, `IG_BOT_EMAIL`).
- **No-Cache-Header** auf statischen UI-Routen (behebt "Tab-Leiste nicht
  klickbar" durch gecachtes altes JS).

### Fixed
- Intent-Edges feuerten bei Marker-Wörtern ("supersedes", "ersetzt",
  "statt") gegen fast alle Nodes — begrenzt durch Ähnlichkeits-Schranke.
- Gecachtes altes `app.js` (referenzierte verschwundene Elemente) führte zu
  JS-Crash → Tabs wirkten tot; durch Cache-Busting + No-Store gelöst.

## [0.1.1] - 2026-08-22

### Added
- Web-UI-Cockpit (`/` + `/review`), FastAPI-Server, WebSocket-Live-Update.
- CLI: `ingest`, `pending`, `accept`, `reject`, `link`, `search`.

## [0.1.0] - 2026-08-22

### Added
- Brain-Layer als privates Git-Repo (Nodes als Markdown, Edges als JSONL,
  Embedding-Cache, INDEX.md).
- Embedder: sentence-transformers (all-MiniLM-L6-v2) + deterministischer
  HashEmbedder für Tests.
- Dedupe (Kosinus ≥ 0.92 → Merge statt Neuanlage).

## [0.0.1] - 2026-08-21

### Added
- Erstes lauffähiges Grundgerüst: Ingest → Embed → Suggest-Ansatz,
  Similarity-Edges (`ähnlich`, `erweitert`), README, MIT-Lizenz.

[Unreleased]: https://github.com/SaltKing0/ideagraph-live/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/SaltKing0/ideagraph-live/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/SaltKing0/ideagraph-live/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/SaltKing0/ideagraph-live/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/SaltKing0/ideagraph-live/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/SaltKing0/ideagraph-live/releases/tag/v0.0.1
