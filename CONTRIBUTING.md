# Contributing to IdeaGraph Live Engine

Thanks for helping out! Here are the key rules to keep things running smoothly.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"   # engine + dev dependencies (pytest)
```

## Tests

All tests run deterministically with the HashEmbedder (no model download):

```bash
.venv/bin/python -m pytest tests/ -q
```

Before a PR: the full suite must be green (`82 passed`). New features need
tests — in particular the golden-set evals (`ideagraph/evals.py`) and the
intent/hygiene integrations.

## Code style

- **Python 3.10+** (uses `str | None` type hints). Type hints are required.
- **No external dependencies** beyond those listed in `pyproject.toml`.
- **Deterministic & stdlib-friendly:** heuristics (e.g. intent detection)
  should work without an NLP dependency and stay testable.
- Comments are in German (consistent with the existing code).

## Architecture notes

- `ideagraph/` = engine logic, `docs/` = frontend (d3), `tests/` = pytest.
- **Brain and engine are separate:** the engine is generic and points to the
  user's brain via `IG_BRAIN_PATH`. No hardcoded personal remote or private
  data in the repo.
- Document env vars: add new options to the `README.md` (env table) and to
  `brain_engine.py` as a constant + `*_from_env()` helper.

## Release

Packaging via `pyproject.toml`, console script `ig`. Bump the version in
`pyproject.toml` and the git tag together. CI (GitHub Actions) runs on
push/PR and must be green.

## Issues / PRs

- Bug report: reproduction steps + expected vs. actual behavior.
- Feature idea: open an issue to discuss first, then a PR.
- PR: small, focused scope; include tests; CI green.

## License

MIT — see `LICENSE`.
