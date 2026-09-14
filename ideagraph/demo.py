"""ideagraph.demo — a small, generic seed brain for onboarding (`ig init --demo`).

13 nodes over generic LLM/agent topics (no user-specific content), linked with
every edge type (aehnlich, erweitert, kontradiktorisch, supersedes, same_as),
2 pending edges for the HITL review flow, an orphan island to demo `ig status`,
and 1 near-dup pair (0.78-0.92 band) to demo `ig near-dup` + `ig merge`.

Everything is deterministic and public-safe: no private data, no personal
defaults, texts written in neutral German with ae/oe/ue/ss only (the demo
mirrors the marker-free finding style used by the self-evolving pipeline).
"""
from __future__ import annotations

import datetime as _dt

from .brain import Brain, Edge, Node

# (text, ntype, tags) — texts reuse each other's vocabulary so the edges are
# semantically honest, not arbitrary.
_NODES: list[tuple[str, str, list[str]]] = [
    # 0: RAG hub
    ("Retrieval-Augmented Generation verbindet ein Sprachmodell mit einer"
     " externen Wissensquelle: der Retriever holt fuer eine Anfrage relevante"
     " Passagen aus einem Korpus, und das Sprachmodell erzeugt die Antwort"
     " grounding auf diesen Passagen. RAG ergaenzt parametrisches Wissen um"
     " adressierbares, aktualisierbares Wissen und reduziert Halluzinationen"
     " bei wissensintensiven Aufgaben.", "semantic", ["rag"]),
    # 1: dense retrieval
    ("Dense Retrieval berechnet fuer Anfrage und Dokumente dichte Vektoren"
     " (Embeddings) und ruft nach Kosinus-Aehnlichkeit ab. Bi-Encoder"
     " encodieren Anfrage und Dokument unabhaengig und erlauben"
     " Approximate-Nearest-Neighbor-Indexe fuer grosse Korpora. Dense"
     " Retrieval haengt zusammen mit RAG als dessen Abruf-Schicht.",
     "semantic", ["retrieval"]),
    # 2: BM25
    ("BM25 ist eine lexikalische Ranking-Funktion auf invertierten Indexen:"
     " Term-Frequenz, inverse Dokument-Frequenz und Laengen-Normalisierung"
     " gewichten Match-Terme. BM25 ergaenzt Dense Retrieval um exakte"
     " Termbefunde wie Namen, IDs und Code-Bezeichner, die Vektor-Aehnlichkeit"
     " verfehlen kann.", "semantic", ["retrieval", "bm25"]),
    # 3: hybrid search (near-dup pair with 2)
    ("Hybride Suche kombiniert lexikalisches Ranking und Dense Retrieval per"
     " Reciprocal Rank Fusion: jeder Ranker liefert eine Rangliste, die Fusion"
     " mischt sie ohne Kalibrierungsschritt. Hybride Suche ergaenzt"
     " Vektor-Aehnlichkeit um exakte Termbefunde und haengt zusammen mit RAG"
     " als Abruf-Schicht.", "semantic", ["retrieval", "hybrid"]),
    # 4: agent memory
    ("Agenten-Memory speichert Erfahrungen eines Agenten ueber Sessions hinweg"
     " in einem persistenten Speicher: episodische Eintraege, semantische"
     " Eintraege und prozedurale Eintraege. Agenten-Memory haengt zusammen mit"
     " RAG, das dieselbe Abruf-Infrastruktur fuer Erinnerung nutzt.",
     "semantic", ["memory"]),
    # 5: episodic memory
    ("Episodisches Memory speichert Ereignisse mit Zeitstempel und Kontext:"
     " Sessions, Entscheidungen, Beobachtungen. Es ergaenzt semantisches"
     " Memory um die zeitliche Dimension und liefert die Grundlage fuer"
     " Konsolidierung: wiederkehrende Episoden generalisieren zu semantischem"
     " Wissen.", "episodic", ["memory", "episodic"]),
    # 6: semantic memory
    ("Semantisches Memory haelt verallgemeinertes Wissen: Konzepte, Fakten,"
     " Regeln. Es entsteht durch Konsolidierung aus episodischen Eintraegen"
     " und bildet die langfristige Wissensbasis eines Agenten.",
     "semantic", ["memory", "semantic"]),
    # 7: graph-RAG
    ("Graph-RAG erweitert RAG um einen Wissensgraphen: Entitaeten und"
     " Relationen werden aus dem Korpus extrahiert, der Retriever traversiert"
     " den Graphen fuer Multi-Hop-Fragen. Graph-RAG zeigt die Grenze rein"
     " lokaler Abrufe bei Fragen, die mehrere Dokumente verbinden.",
     "semantic", ["rag", "graph"]),
    # 8: consolidation (ISLAND — 0 edges, demos `ig status`)
    ("Wissensgraph-Konsolidierung fuehrt semantisch identische Entitaeten"
     " zusammen und haelt den Graphen kompakt: Near-Duplicate-Erkennung per"
     " Embedding-Aehnlichkeit, Redirect von Kanten auf den Survivor, und die"
     " Herkunft bleibt in der Git-Historie erhalten.", "semantic", ["hygiene"]),
    # 9: hallucination
    ("Halluzination bezeichnet fluent klingende, faktisch ungestuetzte"
     " Ausgaben von Sprachmodellen. Grounding auf retrieved Passagen"
     " reduziert Halluzinationen; Zitation der Quellen macht Antworten"
     " ueberpruefbar. Halluzination ist die Hauptmotivation fuer RAG.",
     "semantic", ["safety"]),
    # 10: enterprise RAG
    ("RAG fuer Enterprise-Wissen indexiert interne Dokumente wie Wikis,"
     " Handbuecher und Tickets und beantwortet Mitarbeiterfragen grounding"
     " auf den Dokumenten mit Zitation. Enterprise-RAG ist der haeufigste"
     " Produktions-Einsatz von RAG.", "semantic", ["rag", "enterprise"]),
    # 11: multi-hop (near-dup pair with 7 — measured cos ≈ 0.83 on the demo texts)
    ("Multi-Hop-Fragen ueber einen Wissensgraphen beantwortet Graph-RAG durch"
     " Traversierung extrahierter Entitaeten und Relationen: erst Entitaet A"
     " finden, dann ueber die Relation von A zu B, dann zu C. Der"
     " Graph-RAG-Ansatz traversiert hierfuer den Wissensgraphen; reines"
     " Dense Retrieval versagt, weil keine einzelne Passage die Antwort"
     " haelt.", "semantic", ["rag", "multi-hop"]),
    # 12: same_as demo pair (EN twin of node 0) — demos `ig link` + same_as
    ("Retrieval-Augmented Generation (RAG) connects a language model with an"
     " external knowledge source: the retriever fetches passages relevant to"
     " a query from a corpus, and the language model generates the answer"
     " grounded on those passages.", "semantic", ["rag", "en"]),
]

# (source_idx, target_idx, kind, pending, confidence)
_EDGES: list[tuple[int, int, str, bool, float | None]] = [
    (1, 0, "erweitert", False, None),
    (2, 0, "erweitert", False, None),
    (2, 1, "erweitert", False, None),   # BM25 complements dense retrieval
    (3, 1, "erweitert", False, None),   # hybrid search builds on dense retrieval
    (3, 0, "erweitert", False, None),
    (4, 0, "erweitert", False, None),
    (9, 0, "erweitert", False, None),
    (10, 0, "erweitert", False, None),
    (11, 7, "erweitert", False, None),
    (4, 5, "erweitert", False, None),
    (4, 6, "erweitert", False, None),
    (5, 6, "aehnlich", False, None),
    (7, 0, "supersedes", False, None),        # intent demo: graph-RAG supersedes plain RAG
    (9, 10, "kontradiktorisch", False, None),  # intent demo (explicitly labeled demo pair)
    (3, 2, "aehnlich", False, 0.85),         # near-dup demo pair (hybrid ≈ BM25)
    (0, 12, "same_as", False, None),           # DE/EN alias demo
    (9, 12, "erweitert", False, None),   # hallucination motivates the EN twin too
    # 2 pending edges → the HITL review flow has something to review
    (10, 4, "erweitert", True, 0.62),
    (11, 3, "erweitert", True, 0.58),
]


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_demo_brain(path: str, commit: bool = True) -> dict:
    """Create a fresh brain at `path` and fill it with the demo graph.

    Returns a small stats dict for the CLI to print. Aborts if the path
    already contains a brain (never overwrites user data).
    """
    import os
    if os.path.exists(path) and os.listdir(path):
        raise FileExistsError(f"{path} existiert bereits und ist nicht leer.")
    brain = Brain(path, mode="git")
    brain.init(commit=False)  # structure + git init, no commit yet

    nodes = [Node(text=t, source="demo-seed", tags=tags, ntype=nt, status="active")
             for t, nt, tags in _NODES]
    for n in nodes:
        brain.write_node(n)

    for s, t, kind, pending, conf in _EDGES:
        brain.add_edge(Edge(source=nodes[s].id, target=nodes[t].id,
                            kind=kind, pending=pending, confidence=conf))

    # Embedding cache for the demo nodes (so `ig search` works immediately).
    from .embedder import Embedder
    emb = Embedder()
    vectors = {n.id: emb.embed(n.text) for n in nodes}
    brain.write_vectors(vectors)

    brain.rebuild_index()
    if commit:
        brain.commit_and_push("demo-seed: 13 Nodes, 19 Edges (Beispiel-Graph)",
                              push=False)
    return {"nodes": len(nodes), "edges": len(_EDGES),
            "pending": sum(1 for e in _EDGES if e[3]), "path": str(brain.path)}
