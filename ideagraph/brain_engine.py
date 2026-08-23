"""Wachstums-Loop auf Brain-Basis: ingest → embed → suggest → commit.

Jeder Ingest ist ein Git-Commit im privaten Repo — der Graph wächst
als sichtbare Commit-Historie.
"""

from __future__ import annotations

import os

from .brain import Brain, Node, Edge
from .embedder import get_embedder
from .similarity import cosine
from .suggester import suggest, is_auto_accept
from .intent import detect_intent
from .reranker import get_reranker

DEDUPE_THRESHOLD = 0.92
# Intent-Edges dürfen nur für Paare feuern, die auch wirklich thematisch
# verwandt sind (gleiche Schwelle wie "erweitert"). Ohne diese Schranke würde
# ein Marker-Wort im neuen Text ("ersetzt", "supersedes") eine Node gegen
# JEDE bestehende Node als Intent nachordnen — in einem thematisch homogenen
# Brain (geteilte Domänenvokabeln) sogar gegen fast alle.
INTENT_SIM_THRESHOLD = 0.45
AUTO_ACCEPT_ENV = "IDEAGRAPH_AUTO_ACCEPT"  # "1"/"true" → Edges werden ohne HITL akzeptiert
# "1"/"true" → Intent-Edges (supersedes/continues/kontradiktorisch) werden
# pending (HITL-Review) statt auto-akzeptiert. Lässt Nutzer frei entscheiden,
# ob automatisch erkannte Intentionen direkt in den Graph sollen.
INTENT_PENDING_ENV = "IDEAGRAPH_INTENT_PENDING"


def auto_accept_from_env() -> bool:
    return os.environ.get(AUTO_ACCEPT_ENV, "").lower() in ("1", "true", "yes")


def intent_pending_from_env() -> bool:
    return os.environ.get(INTENT_PENDING_ENV, "").lower() in ("1", "true", "yes")


def _normalize(text: str) -> str:
    """Für den Duplikats-Vergleich: Kleinbuchstaben, Whitespace eingeebnet."""
    return " ".join(text.lower().split())


class BrainEngine:
    def __init__(self, brain: Brain, embedder=None, dedupe_threshold: float = DEDUPE_THRESHOLD,
                 reranker=None):
        self.brain = brain
        self.embedder = embedder if embedder is not None else get_embedder()
        self.dedupe_threshold = dedupe_threshold
        # V2#1: optionaler Cross-Encoder-Rerank-Pass; None/Default → kein Rerank.
        self.reranker = reranker if reranker is not None else get_reranker()

    def _find_duplicate(self, vec: list[float], exclude_id: str | None = None) -> Node | None:
        """Nächster Node über dem Dedupe-Threshold — oder None. Nutzt den Vektor-Cache."""
        node_ids = {n.id for n in self.brain.read_nodes() if n.id != exclude_id}
        vectors = self.brain.vectors_for(node_ids, lambda t: self.embedder.embed(_normalize(t)))
        best: tuple[float, str] | None = None
        for nid, v in vectors.items():
            sim = cosine(vec, v)
            if sim >= self.dedupe_threshold and (best is None or sim > best[0]):
                best = (sim, nid)
        if best is None:
            return None
        return next((n for n in self.brain.read_nodes() if n.id == best[1]), None)

    def consolidate(self, admit_required: bool = False) -> dict:
        """Dedup-basierte Consolidation (V2#2): Dual-Buffer-Promotion.

        Prüft alle Probation-Nodes GEGENEINANDER und gegen active (schließt den
        Streaming-Blindfleck: im selben Commit ingestierte Nodes wurden bisher
        nie verglichen). Near-Duplicates werden GEMERGT (Dedupe, niemals
        summarize) und der überflüssige Probation-Node getombstoned; alle
        übrigen werden nach active promoted.

        `admit_required` (V2#3 Admit-Rule, opt-in): wenn True, tritt eine Node
        nur in den aktiven Graph ein, wenn sie Relationen (aktive Edges) hat —
        sonst bleibt sie in probation. Default False = bestehendes Verhalten
        (promote alle).
        """
        promoted, merged = 0, 0
        for pn in self.brain.read_nodes():
            if pn.status != "probation":
                continue
            pvec = self.brain.vectors_for(
                {pn.id}, lambda t: self.embedder.embed(_normalize(t))
            ).get(pn.id)
            dup = self._find_duplicate(pvec, exclude_id=pn.id) if pvec else None
            if dup is not None and dup.status != "tombstone":
                self.brain.merge_node(dup, source=pn.source)
                self.brain.tombstone_node(pn.id)
                merged += 1
                continue
            # V2#3 Admit-Rule (opt-in): ohne Relationen (aktive Edges) tritt die
            # Node nicht in den aktiven Graph ein — sie bleibt in probation.
            if admit_required and not self._has_relation(pn.id):
                continue
            self.brain.promote_node(pn.id)
            promoted += 1
        if promoted or merged:
            self.brain.rebuild_index()
        return {"promoted": promoted, "merged": merged}

    def _has_relation(self, node_id: str) -> bool:
        """V2#3 Admit-Rule: hat die Node eine aktive Edge (ein-/ausgehend)?"""
        return any(e.source == node_id or e.target == node_id
                   for e in self.brain.read_edges() if e.valid_to is None)

    def demote_forgotten(self, level_fn) -> int:
        """Graceful Degradation (V2#2): aktive Nodes, deren level_fn=='tombstone'
        ist, werden getombstoned (nie hart gelöscht). level_fn(node)->str liefert
        die Decay-Stufe (z. B. aus decay.decay_level mit Retrieval-Zählern)."""
        count = 0
        for n in self.brain.read_nodes():
            if n.status == "active" and level_fn(n) == "tombstone":
                self.brain.tombstone_node(n.id)
                count += 1
        if count:
            self.brain.rebuild_index()
        return count

    def ingest(self, text: str, source: str = "human", tags: list[str] | None = None,
               allow_duplicates: bool = False, ntype: str = "semantic",
               auto_accept: bool | None = None,
               relations: list[tuple[str, str]] | None = None) -> tuple[Node, list[Edge], bool]:
        """Ingest mit Dedupe. Rückgabe: (node, edges, is_duplicate).

        Bei Near-Duplicate (cosine >= threshold gegen normalisierten Text)
        wird kein neuer Node angelegt, sondern der bestehende gemergt:
        Quelle wird an der Node protokolliert, Commit-Meldung sagt "dup".
        auto_accept (default: Env IDEAGRAPH_AUTO_ACCEPT) akzeptiert
        Edge-Vorschläge direkt statt sie pending zu lassen.
        """
        if auto_accept is None:
            auto_accept = auto_accept_from_env()
        intent_pending = intent_pending_from_env()
        text = text.strip()
        if not text:
            raise ValueError("Leerer Text kann nicht ingestiert werden.")
        self.brain.pull()
        vec = self.embedder.embed(_normalize(text))
        if not allow_duplicates:
            dup = self._find_duplicate(vec)
            if dup is not None:
                self.brain.merge_node(dup, source=source)
                self.brain.rebuild_index()
                self.brain.commit_and_push(
                    f"ingest dup of {dup.id[:8]}: {_normalize(text)[:50]}…")
                return dup, [], True
        node = Node(text=text, source=source, tags=tags, ntype=ntype)
        self.brain.write_node(node)
        # Embedding-Cache: nur neue Nodes werden embeddet, Rest kommt aus vectors.jsonl
        others = {n.id for n in self.brain.read_nodes() if n.id != node.id}
        candidates = self.brain.vectors_for(others, lambda t: self.embedder.embed(_normalize(t)))
        # V2#3 Intent-Edges + Admit-Rule: die neue Node tritt mit ihren Relationen ein.
        # Intent-Edges sind pending=False (automatisch akzeptiert), deshalb müssen
        # sie zusätzlich eine echte thematische Verwandtschaft nachweisen (ST-Kosinus
        # >= INTENT_SIM_THRESHOLD), sonst spammt ein Marker-Wort alle Nodes voll.
        intent_edges: list[Edge] = []
        for ex in self.brain.read_nodes():
            if ex.id == node.id:
                continue
            intent = detect_intent(node.text, ex.text)
            if not intent:
                continue
            ex_vec = candidates.get(ex.id)
            if ex_vec is None or cosine(vec, ex_vec) < INTENT_SIM_THRESHOLD:
                continue
            intent_edges.append(Edge(source=node.id, target=ex.id, kind=intent, pending=intent_pending))
        # Admit-Rule: explizit deklarierte Relationen (target_text|id, kind).
        if relations:
            for ref, kind in relations:
                target = next((n for n in self.brain.read_nodes()
                               if n.id == ref or n.text.strip().lower() == ref.strip().lower()), None)
                if target is not None and target.id != node.id:
                    intent_edges.append(Edge(source=node.id, target=target.id, kind=kind, pending=False))
        # Similarity-Edges (V2#3): pending nur, wenn weder das Confidence-Band (>=0.95)
        # noch der Env-Override (IDEAGRAPH_AUTO_ACCEPT) die Edge auto-akzeptiert.
        sim_edges = [Edge(source=s.source, target=s.target, kind=s.kind,
                          pending=not (is_auto_accept(s.confidence) or auto_accept),
                          confidence=s.confidence)
                     for s in suggest(node.id, vec, candidates)]
        # Intent/Admit-Rule-Edges haben Vorrang; Similarity darf dieselbe Pair nicht duplizieren.
        claimed = {(e.source, e.target) for e in intent_edges}
        combined = list(intent_edges)
        for e in sim_edges:
            if (e.source, e.target) in claimed:
                continue
            claimed.add((e.source, e.target))
            combined.append(e)
        existing_pairs = {(e.source, e.target) for e in self.brain.read_edges()}
        new_edges = [e for e in combined if (e.source, e.target) not in existing_pairs]
        for e in new_edges:
            self.brain.add_edge(e)
        # Vektor der neuen Node cachen
        cached = self.brain.read_vectors()
        cached[node.id] = vec
        self.brain.write_vectors(cached)
        # Memory Evolution (A-Mem-Lektion): starke neue Verbindung (ähnlich,
        # auto-akzeptiert via Confidence-Band ODER Env) → verwandte Alt-Nodes
        # mit Querverweis anreichern.
        evolved = 0
        for e in new_edges:
            if not e.pending and e.kind == "ähnlich":
                    target_node = next((n for n in self.brain.read_nodes()
                                        if n.id == e.target), None)
                    if target_node is not None:
                        ref = f"[evolved {self._now_short()}: vernetzt mit {node.id[:8]} „{_normalize(text)[:40]}…“]"
                        if "evolved" not in target_node.text or node.id[:8] not in target_node.text:
                            self.brain.write_node(Node(
                                text=target_node.text + "\n\n" + ref,
                                id=target_node.id, created=target_node.created,
                                source=target_node.source, tags=target_node.tags,
                                sources=getattr(target_node, 'sources', []),
                                ntype=target_node.ntype))
                            evolved += 1
        self.brain.rebuild_index()
        suffix = f", {evolved} Nodes evolviert" if evolved else ""
        self.brain.commit_and_push(
            f"ingest: {text[:50]}{'…' if len(text) > 50 else ''} (+{len(new_edges)} Vorschläge{suffix})")
        return node, new_edges, False

    @staticmethod
    def _now_short() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def resolve(self, edge_id: str, accept: bool) -> Edge | None:
        self.brain.pull()
        edge = self.brain.resolve_edge(edge_id, accept)
        if edge is not None:
            action = "accept" if accept else "reject"
            self.brain.commit_and_push(f"edge {action}: {edge_id[:8]} [{edge.kind}]")
        return edge

    def link(self, source_id: str, target_id: str,
             kind: str = "same_as") -> Edge:
        """Manuelle Edge anlegen (z.B. same_as für Übersetzungs-/Alias-Paare)."""
        self.brain.pull()
        ids = {n.id for n in self.brain.read_nodes()}
        missing = [nid for nid in (source_id, target_id) if nid not in ids]
        if missing:
            raise ValueError(f"Node(s) nicht gefunden: {', '.join(missing)}")
        existing_pairs = {(e.source, e.target) for e in self.brain.read_edges()}
        if (source_id, target_id) in existing_pairs:
            raise ValueError("Diese Edge existiert bereits.")
        edge = Edge(source=source_id, target=target_id, kind=kind, pending=False)
        self.brain.add_edge(edge)
        self.brain.commit_and_push(f"edge link: {source_id[:8]} --[{kind}]--> {target_id[:8]}")
        return edge
