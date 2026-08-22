# IdeaGraph Live Engine 🕸️

**Selbstwachsender Ideen-Graph: Ingest → Embed → Suggest → Visualize**

v0.0.1 — von scratch, lernorientiert. Keine Graph-DB, keine Viz-Lib außer d3-force.

## Idee

Ideen als Nodes, Beziehungen als getypte Edges (`ähnlich`, `kontradiktorisch`, `erweitert`).
Neue Ideen werden reingegeben (Ingest), lokal embedded, mit dem besten Nachbarn
verglichen — der Graph schlägt selbst Edges vor, du entscheidest (Human-in-the-loop).

## Wachstums-Loop

```
Text ──▶ Embedding ──▶ k-NN Suche ──┬─▶ Edge-Vorschlag (pending)
                                    └─▶ Node im Graph (WebSocket Live-Update)
```

## Quickstart

```bash
python3 -m venv --without-pip .venv && .venv/bin/pip install -r requirements.txt
echo "Emergenz entsteht aus einfachen Regeln" | python -m ideagraph ingest -
uvicorn ideagraph.server:app --reload
# → http://localhost:8000
```

Im Web-UI: pending Edges per Klick akzeptieren oder verwerfen.

## Struktur

```
ideagraph/       Kern: Modell, Store (JSONL), Embedder, Suggester, Server
tests/           Similarity + Edge-Vorschlag
docs/            Frontend (GitHub Pages): d3-force Graph, ohne lokalen Server lesbar
data.jsonl       Deine Daten — wird nicht committet (*.jsonl ignoriert)
```

## Embeddings

Lokal via `sentence-transformers` (Default: `all-MiniLM-L6-v2`, läuft auf CPU).
Kein Ollama nötig — alles Python, keine externen Dienste.

## Status

Still in the making.
