# IdeaGraph Live Engine 🕸️

**Selbstwachsender Ideen-Graph: Ingest → Embed → Suggest → Visualize**

Eine generische Engine für einen persistenten Wissensgraph aus Ideen. Das
Gedächtnis ist **dein eigenes privates Git-Repo** (der "Brain") — die Engine
ist vom Brain entkoppelt und zeigt per `IG_BRAIN_PATH` auf deinen Clone.
Kein hardcoded Remote, keine privaten Daten im Code: open-source-tauglich.

## Web-UI (Cockpit mit Tabs)

Starte den Server, öffne die URL, und du bekommst ein Cockpit mit drei Tabs:

| Tab | Funktion |
|---|---|
| **Ingest** (Start) | Neue Ideen/Notizen erfassen (Quelle wählbar), Duplikat-Merge, Status |
| **Graph** | d3-Force-Graph mit Zoom/Pan (Obsidian-artig): Scroll = Zoom, Ziehen = Pan, Hover = Tooltip, Klick = Details, Doppelklick = Fokus (Nachbarn hervorheben), Suche = zentrieren |
| **Review** | Pending-Edge-Vorschläge akzeptieren/verwerfen + `same_as`-Picker |

Tastatur: `1/2/3` Tabs · `i` Ingest · `Space` Node-Text · `Esc` schließen ·
`j/k/Enter` Review-Navigation.

```
uvicorn ideagraph.server:app --host 127.0.0.1 --port 8000   # → http://localhost:8000
```

## Architektur

```
┌──────────────┐   git commit+push   ┌────────────────────┐   git pull   ┌─────────────────┐
│ Hermes Agent │ ──────────────────▶ │ dein Brain-Repo    │ ◀──────────▶ │ Live Engine     │
│ (Discord/CLI)│    (Wissen, gelerntes) │ (privat, Markdown)│  (sync)      │ Ingest→Embed→   │
└──────────────┘                     └────────────────────┘              Suggest→Viz+HITL │
                                                                          └─────────────────┘
```

- **Nodes** = eine Markdown-Datei pro Idee (`nodes/<id>.md`, YAML-Frontmatter
  mit `type: semantic|episodic|procedural`, `status: probation|active|tombstone`,
  `sources:` protokolliert gemergte Duplikat-Ingests)
- **Edges** = `edges.jsonl` (getypt: `ähnlich`, `erweitert`, `kontradiktorisch`,
  `supersedes`, `continues`, `same_as`; bi-temporal: `valid_from`/`valid_to` —
  Invalidierung statt Löschung; Confidence + Provenance)
- **vectors.jsonl** = Embedding-Cache (nur neue Nodes werden embeddet)
- **INDEX.md** = generiertes Inhaltsverzeichnis
- Jeder Ingest ist ein Commit — der Graph wächst als sichtbare Historie.

## Features (Roadmap V2, umgesetzt)

- **Confidence + Auto-Accept-Band** — Similarity-Edges ≥ 0.95 werden direkt
  akzeptiert, sonst pending (HITL); `IDEAGRAPH_AUTO_ACCEPT=1` erzwingt.
- **Hybrid-Retrieval** — dense + BM25 via RRF-Fusion (`ig search`).
- **Intent-Edges (V2#3)** — automatisch erkannte Intentionen `supersedes` /
  `kontradiktorisch` / `continues` per Marker-Heuristik. Sicherheits-Schranke:
  nur bei echtem ST-Kosinus ≥ 0.45 (verhindert Fehltreffer in homogenen
  Korpora). ⚠️ Intent-Edges sind aktuell auto-akzeptiert (nicht pending) —
  siehe „Pre-Release-Überlegungen".
- **Memory-Hygiene (V2#2)** — Dual-Buffer: neue Nodes starten in `probation`,
  werden nach Dedup-Verifikation `active` oder `tombstone` (Graceful
  Degradation, nie hart löschen); Weibull-Decay.
- **Snapshot-Persistenz** — jeder Ingest ist ein git-Commit; bi-temporale
  Edges + Provenance (`invalidated_by`).

## CLI

```bash
ig ingest "Neue Idee ..."          # Ingest (Duplikate werden gemergt)
cat notiz.md | ig ingest -         # aus Datei/Stdin
ig pending                         # offene Edge-Vorschläge
ig accept <edge_id>                # Vorschlag akzeptieren
ig reject <edge_id>                # Vorschlag verwerfen
ig link <node_a> <node_b>          # manuelle Edge (default: same_as)
ig search "attention"              # Hybrid-Suche (dense + BM25)
```

## Edge-Typen

| Typ | Entstehung | Bedeutung |
|---|---|---|
| `ähnlich` | automatisch (sim ≥ 0.75) | im Wesentlichen dieselbe Idee |
| `erweitert` | automatisch (0.45–0.75) | thematisch verwandt, baut auf |
| `supersedes` | Intent (Marker + sim ≥ 0.45) | neu ersetzt/obsolet macht alt |
| `continues` | Intent (Marker + sim ≥ 0.45) | führt fort / baut auf |
| `kontradiktorisch` | Intent/manuell | widerspricht sich |
| `same_as` | nur manuell (`ig link`) | Übersetzungs-/Alias-Paar |

## Dedupe

Near-Duplicate-Ingests (Kosinus ≥ 0.92 auf normalisiertem Text) werden
**gemergt statt neu angelegt**: die Quelle landet im Frontmatter unter
`sources:`, der Commit sagt `ingest dup of …`. Opt-out: `allow_duplicates: true`.

## Node-Typen

| Typ | Bedeutung | Beispiele |
|---|---|---|
| `semantic` | Fakten, Ideen, Konzepte (Default) | Papers, Projekt-Notizen |
| `episodic` | Ereignisse, Session-Logs | „Subagent X lief heute Y" |
| `procedural` | Skills, wiederverwendbare Prozeduren | „So ingestiert man Research" |

## Quickstart

```bash
# 1) dein eigenes Brain-Repo einmalig klonen (Remote nur hier nötig):
git clone <dein-brain-repo> ~/ideagraph-brain

# 2) Engine einrichten (Python 3.10+)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3) Server starten
#   Demo ohne Modell-Download:  IDEAGRAPH_EMBEDDER=hash uvicorn ideagraph.server:app --host 127.0.0.1 --port 8000
#   Echt (lädt all-MiniLM-L6-v2): uvicorn ideagraph.server:app --host 127.0.0.1 --port 8000

# 4) CLI-Ingest
.venv/bin/python -m ideagraph ingest "Neue Idee ..."
# → http://localhost:8000 — Ingest/Graph/Review-Tabs
```

### Env-Variablen

| Variable | Default | Bedeutung |
|---|---|---|
| `IG_BRAIN_PATH` | `~/ideagraph-brain` | Pfad zum Brain-Clone |
| `IG_BRAIN_REMOTE` | *(keiner)* | nur für `git clone` beim ersten Einrichten; Bestandsklones nutzen ihr eigenes origin |
| `IG_BRAIN_MODE` | `git` | `local` = nur FS (Tests) |
| `IDEAGRAPH_EMBEDDER` | `st` | `hash` = deterministischer Test-Embedder |
| `IDEAGRAPH_AUTO_ACCEPT` | aus | `1` = Edges werden automatisch akzeptiert (kein HITL) |
| `IG_BOT_NAME` | `ideagraph-bot` | Git-Commit-Autor (Name) |
| `IG_BOT_EMAIL` | `bot@ideagraph.local` | Git-Commit-Autor (E-Mail) |

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

81 Tests — Similarity, Edge-Vorschlag, Intent, Dedupe, Memory-Hygiene,
Markdown-Roundtrip, Brain-FS, Retrieval, Evals (Golden-Set).

## Open Source / Datenschutz

- Die **Engine ist generisch** (öffentliches Repo) — der **Brain ist dein
  privates Repo** mit deinen Daten. Die Engine enthält keine Brain-Daten.
- Der Server bindet standardmäßig auf `127.0.0.1`; für Fernzugriff einen
  SSH-Tunnel nutzen, damit dein Wissensgraph nicht öffentlich exponiert wird.
- Keine hardcoded persönlichen Remote/Identitäten im Code; alle über Env
  konfigurierbar.

## Status

In Entwicklung. Nächster Schritt: Discord-Agent schreibt automatisch ins Brain.

## Pre-Release-Überlegungen

- **Intent-Edges als Config-Option (HITL):** Aktuell auto-akzeptiert (nicht
  pending), aber durch die Ähnlichkeits-Schranke (ST-Kosinus ≥ 0.45) eingegrenzt.
  Vor dem Release prüfen, ob Intent-Edges optional auf `pending` (HITL-Review)
  umstellbar sein sollen. Entscheidung offen.
- **Packaging:** `pyproject.toml` + `ig`-Console-Script + CI fehlen noch (siehe
  Release-Checkliste) — dann ist das Projekt sauber pip-installierbar und
  CI-geprüft.
