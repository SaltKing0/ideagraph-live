# Contributing to IdeaGraph Live Engine

Danke, dass du mithelfen willst! Hier die wichtigsten Regeln, damit alles
reibungslos läuft.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"   # Engine + Dev-Abhängigkeiten (pytest)
```

## Tests

Alle Tests laufen deterministisch mit dem HashEmbedder (kein Modell-Download):

```bash
.venv/bin/python -m pytest tests/ -q
```

Vor einem PR: Die volle Suite muss grün sein (`82 passed`). Neue Features
brauchen Tests — insbesondere die Golden-Set-Evals (`ideagraph/evals.py`)
und die Intent-/Hygiene-Integrationen.

## Code-Stil

- **Python 3.10+** (nutzt `str | None`-Typ-Hints). Type-Hints sind Pflicht.
- **Keine externen Dependencies** außer den in `pyproject.toml` gelisteten.
- **Deterministisch & stdlib-freundlich:** Heuristiken (z.B. Intent-Erkennung)
  sollen ohne NLP-Dependency auskommen und testbar sein.
- Kommentare auf Deutsch (konsistent mit dem Code).

## Architecture-Hinweise

- `ideagraph/` = Engine-Logik, `docs/` = Frontend (d3), `tests/` = pytest.
- **Brain vs. Engine sind getrennt:** Die Engine ist generisch und zeigt per
  `IG_BRAIN_PATH` auf den Nutzer-Brain. Kein hardcoded persönlicher Remote
  oder private Daten im Repo.
- Env-Variablen dokumentieren: neue Optionen in `README.md` (Env-Tabelle) und
  in `brain_engine.py` als Konstante + `*_from_env()`-Helfer ergänzen.

## Release

Packaging via `pyproject.toml`, Console-Script `ig`. Version in
`pyproject.toml` + Git-Tag gemeinsam erhöhen. CI (GitHub Actions) läuft auf
Push/PR und muss grün sein.

## Issues / PRs

- Bug-Report: Schritt zur Reproduktion + erwartetes vs. tatsächliches Verhalten.
- Feature-Idee: erst als Issue diskutieren, dann PR.
- PR: kleiner, fokussierter Scope; Tests inklusive; CI grün.

## Lizenz

MIT — siehe `LICENSE`.
