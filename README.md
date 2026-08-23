# IdeaGraph Live Engine 🕸️

**Selbstwachsender Ideen-Graph: Ingest → Embed → Suggest → Visualize**

v0.1.4 — Autonomie-Modus (IDEAGRAPH_AUTO_ACCEPT), Review-UI (/review). Das Gedächtnis ist dein eigenes privates Git-Repo (z.B. `~/ideagraph-brain`) — die Engine ist generisch und zeigt per `IG_BRAIN_PATH` auf deinen Brain.

## Architektur

```
┌──────────────┐   git commit+push   ┌────────────────────┐   git pull   ┌─────────────────┐
│ Hermes Agent │ ──────────────────▶ │ ideagraph-brain    │ ◀──────────▶ │ Live Engine     │
│ (Discord/CLI)│    (Wissen, gelerntes) │ (privat, Markdown)│  (sync)      │ Ingest→Embed→   │
└──────────────┘                     └────────────────────┘              Suggest→Viz+HITL │
                                                                          └─────────────────┘
```

- **Nodes** = eine Markdown-Datei pro Idee (`nodes/<id>.md`, YAML-Frontmatter mit `type: semantic|episodic|procedural`, `sources:` protokolliert gemergte Duplikat-Ingests)
- **Edges** = `edges.jsonl` (getypt: `ähnlich`, `kontradiktorisch`, `erweitert`; bi-temporal: `valid_from`/`valid_to` — Invalidierung statt Löschung; keine Doppel-Vorschläge)
- **vectors.jsonl** = Embedding-Cache (pro Node ein Vektor — nur neue Nodes werden embeddet)
- **INDEX.md** = generiertes Inhaltsverzeichnis
- Jeder Ingest ist ein Commit — der Graph wächst als sichtbare Historie.

## CLI

```bash
alias ig="(cd ~/ideagraph-live && .venv/bin/python -m ideagraph)"

ig ingest "Neue Idee ..."          # Ingest (Duplikate werden gemergt)
cat notiz.md | ig ingest -         # aus Datei/Stdin
ig pending                         # offene Edge-Vorschläge
ig accept <edge_id>                # Vorschlag akzeptieren
ig reject <edge_id>                # Vorschlag verwerfen
ig link <node_a> <node_b>          # manuelle Edge (default: same_as)
ig search "attention"              # Volltext über alle Nodes
```

## Edge-Typen

| Typ | Entstehung | Bedeutung |
|---|---|---|
| `ähnlich` | automatisch (sim ≥ 0.75) | im Wesentlichen dieselbe Idee |
| `erweitert` | automatisch (0.45–0.75) | thematisch verwandt, baut auf |
| `kontradiktorisch` | geplant/manuell | widerspricht sich |
| `same_as` | nur manuell (`ig link`) | Übersetzungs-/Alias-Paar, keine Duplikate |

## Dedupe

Near-Duplicate-Ingests (Kosinus ≥ 0.92 auf normalisiertem Text) werden **gemergt statt neu angelegt**:
die Quelle landet im Frontmatter unter `sources:`, der Commit sagt `ingest dup of …`.
Opt-out pro Ingest: `allow_duplicates: true` (Body-Feld in `/api/ingest`).

## Autonomie-Modus

`IDEAGRAPH_AUTO_ACCEPT=1` akzeptiert Edge-Vorschläge direkt (kein HITL).
Dabei gilt zusätzlich **Memory Evolution** (A-Mem-Muster): starke neue
`ähnlich`-Verbindungen reichern die verwandten Alt-Nodes mit einem
datierten Querverweis an — das Netz verfeinert sich retroaktiv selbst.

## Node-Typen

| Typ | Bedeutung | Beispiele |
|---|---|---|
| `semantic` | Fakten, Ideen, Konzepte (Default) | Papers, Projekt-Notizen |
| `episodic` | Ereignisse, Session-Logs | „Subagent X lief heute Y" |
| `procedural` | Skills, wiederverwendbare Prozeduren | „So ingestiert man Research" |

## Wachstums-Loop

```
Text ──▶ git pull ──▶ Node als .md ──▶ Embedding ──▶ k-NN ──┬─▶ Edge-Vorschlag (pending)
                                                            └─▶ commit + push + WebSocket-Live
```

## Quickstart

```bash
# dein eigenes Brain-Repo einmalig klonen (Remote nur hier nötig):
git clone <dein-brain-repo> ~/ideagraph-brain
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
| `IDEAGRAPH_AUTO_ACCEPT` | aus | `1` = Edge-Vorschläge werden automatisch akzeptiert (Autonomie-Modus, kein HITL) |
| `IG_BRAIN_REMOTE` | *(keiner)* | nur für `git clone` beim ersten Einrichten nötig; Bestandsklones nutzen ihr eigenes origin |
| `IG_BRAIN_MODE` | `git` | `local` = nur FS (Tests) |
| `IDEAGRAPH_EMBEDDER` | `st` | `hash` = deterministischer Test-Embedder |
| `IG_BOT_NAME` | `ideagraph-bot` | Git-Commit-Autor (Name) |
| `IG_BOT_EMAIL` | `bot@ideagraph.local` | Git-Commit-Autor (E-Mail) |

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

24 Tests — Similarity, Edge-Vorschlag, Markdown-Roundtrip, Brain-FS, Engine-Loop, Dedupe.

## Status

Still in the making. Nächster Schritt: Discord-Agent schreibt automatisch ins Brain.
