# IdeaGraph Live Engine 🕸️

**Selbstwachsender Ideen-Graph: Ingest → Embed → Suggest → Visualize**

v0.1.0 — das Gedächtnis ist jetzt ein privates Git-Repo: [ideagraph-brain](https://github.com/your-brain-repo).

## Architektur

```
┌──────────────┐   git commit+push   ┌────────────────────┐   git pull   ┌─────────────────┐
│ Hermes Agent │ ──────────────────▶ │ ideagraph-brain    │ ◀──────────▶ │ Live Engine     │
│ (Discord/CLI)│    (Wissen, gelerntes) │ (privat, Markdown)│  (sync)      │ Ingest→Embed→   │
└──────────────┘                     └────────────────────┘              Suggest→Viz+HITL │
                                                                          └─────────────────┘
```

- **Nodes** = eine Markdown-Datei pro Idee (`nodes/<id>.md`, YAML-Frontmatter)
- **Edges** = `edges.jsonl` (getypt: `ähnlich`, `kontradiktorisch`, `erweitert`; pending bis akzeptiert)
- **INDEX.md** = generiertes Inhaltsverzeichnis
- Jeder Ingest ist ein Commit — der Graph wächst als sichtbare Historie.

## Wachstums-Loop

```
Text ──▶ git pull ──▶ Node als .md ──▶ Embedding ──▶ k-NN ──┬─▶ Edge-Vorschlag (pending)
                                                            └─▶ commit + push + WebSocket-Live
```

## Quickstart

```bash
git clone git@github.com:your-brain-repo.git ~/ideagraph-brain
python3 -m venv --without-pip .venv && .venv/bin/pip install -r requirements.txt

# Demo-Modus (HashEmbedder, kein Modell-Download):
IDEAGRAPH_EMBEDDER=hash uvicorn ideagraph.server:app --reload
# Echt: sentence-transformers lädt all-MiniLM-L6-v2 beim ersten Embedding

echo "Neue Idee" | python -m ideagraph ingest -   # CLI-Ingest
# → http://localhost:8000 — pending Edges per Klick akzeptieren/verwerfen
```

### Env-Variablen

| Variable | Default | Bedeutung |
|---|---|---|
| `IG_BRAIN_PATH` | `~/ideagraph-brain` | Pfad zum Brain-Clone |
| `IG_BRAIN_REMOTE` | `git@github.com:your-brain-repo.git` | Remote-URL |
| `IG_BRAIN_MODE` | `git` | `local` = nur FS (Tests) |
| `IDEAGRAPH_EMBEDDER` | `st` | `hash` = deterministischer Test-Embedder |

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

24 Tests — Similarity, Edge-Vorschlag, Markdown-Roundtrip, Brain-FS, Engine-Loop.

## Status

Still in the making. Nächster Schritt: Discord-Agent schreibt automatisch ins Brain.
