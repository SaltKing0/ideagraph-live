# IdeaGraph Live Engine 🕸️

**Selbstwachsender Ideen-Graph: Ingest → Embed → Suggest → Visualize**

v0.1.2 — Dedupe + Embedding-Cache. Das Gedächtnis ist ein privates Git-Repo: [ideagraph-brain](https://github.com/your-brain-repo).

## Architektur

```
┌──────────────┐   git commit+push   ┌────────────────────┐   git pull   ┌─────────────────┐
│ Hermes Agent │ ──────────────────▶ │ ideagraph-brain    │ ◀──────────▶ │ Live Engine     │
│ (Discord/CLI)│    (Wissen, gelerntes) │ (privat, Markdown)│  (sync)      │ Ingest→Embed→   │
└──────────────┘                     └────────────────────┘              Suggest→Viz+HITL │
                                                                          └─────────────────┘
```

- **Nodes** = eine Markdown-Datei pro Idee (`nodes/<id>.md`, YAML-Frontmatter, `sources:` protokolliert gemergte Duplikat-Ingests)
- **Edges** = `edges.jsonl` (getypt: `ähnlich`, `kontradiktorisch`, `erweitert`; pending bis akzeptiert; keine Doppel-Vorschläge)
- **vectors.jsonl** = Embedding-Cache (pro Node ein Vektor — nur neue Nodes werden embeddet)
- **INDEX.md** = generiertes Inhaltsverzeichnis
- Jeder Ingest ist ein Commit — der Graph wächst als sichtbare Historie.

## Dedupe

Near-Duplicate-Ingests (Kosinus ≥ 0.92 auf normalisiertem Text) werden **gemergt statt neu angelegt**:
die Quelle landet im Frontmatter unter `sources:`, der Commit sagt `ingest dup of …`.
Opt-out pro Ingest: `allow_duplicates: true` (Body-Feld in `/api/ingest`).

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

24 Tests — Similarity, Edge-Vorschlag, Markdown-Roundtrip, Brain-FS, Engine-Loop, Dedupe.

## Status

Still in the making. Nächster Schritt: Discord-Agent schreibt automatisch ins Brain.
