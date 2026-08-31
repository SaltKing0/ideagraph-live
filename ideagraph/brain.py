"""Brain-Layer: das private Git-Repo als Gedächtnis.

Struktur im Brain-Repo:
  nodes/<id>.md     — eine Idee pro Datei (YAML-Frontmatter + Text)
  edges.jsonl       — eine Edge pro Zeile (maschinell, pending-Flag)
  INDEX.md          — generiertes Inhaltsverzeichnis (Menschen + GitHub-Suche)

Sync-Modell: pull vor jedem Schreiben, commit+push danach.
Für Tests: mode="local" arbeitet ohne git in einem temp dir.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


VALID_STATUS = ("probation", "active", "tombstone")


class Node:
    def __init__(self, text: str, id: str | None = None, created: str | None = None,
                 source: str = "human", tags: list[str] | None = None,
                 sources: list[str] | None = None, ntype: str = "semantic",
                 status: str = "probation"):
        self.text = text
        self.id = id or uuid.uuid4().hex[:12]
        self.created = created or _now_iso()
        self.source = source
        self.tags = tags or []
        self.sources = sources or []
        # Taxonomie (LangGraph/Survey-Lektion): semantic | episodic | procedural
        self.ntype = ntype if ntype in ("semantic", "episodic", "procedural") else "semantic"
        # V2#2 Memory-Hygiene: Dual-Buffer — neue Nodes starten in probation,
        # werden nach Dedup/Verification promoted, oder landen als tombstone.
        self.status = status if status in VALID_STATUS else "probation"

    def to_markdown(self) -> str:
        tags = "[" + ", ".join(self.tags) + "]" if self.tags else "[]"
        lines = [f"id: {self.id}", f"created: {self.created}",
                 f"source: {self.source}", f"type: {self.ntype}",
                 f"status: {self.status}"]
        if self.sources:
            lines.append("sources: [" + ", ".join(self.sources) + "]")
        lines.append(f"tags: {tags}")
        return "---\n" + "\n".join(lines) + "\n---\n\n" + f"{self.text}\n"

    @classmethod
    def from_markdown(cls, raw: str) -> "Node":
        m = re.match(r"^---\n(.*?)\n---\n\n?(.*)$", raw, re.DOTALL)
        if not m:
            raise ValueError("Kein Frontmatter gefunden")
        meta_raw, text = m.group(1), m.group(2)
        meta: dict = {}
        for line in meta_raw.splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                meta[key.strip()] = val.strip()
        tags = [t.strip() for t in meta.get("tags", "[]").strip("[]").split(",") if t.strip()]
        sources = [s.strip() for s in meta.get("sources", "").strip("[]").split(",") if s.strip()]
        return cls(text=text.strip(), id=meta["id"], created=meta.get("created"),
                   source=meta.get("source", "human"), tags=tags, sources=sources,
                   ntype=meta.get("type", "semantic"), status=meta.get("status", "probation"))

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "created": self.created,
                "source": self.source, "tags": self.tags, "sources": self.sources,
                "type": self.ntype, "status": self.status}


class Edge:
    def __init__(self, source: str, target: str, kind: str,
                 pending: bool = True, id: str | None = None,
                 valid_from: str | None = None, valid_to: str | None = None,
                 confidence: float | None = None,
                 invalidated_by: str | None = None):
        self.source = source
        self.target = target
        self.kind = kind
        self.pending = pending
        self.id = id or uuid.uuid4().hex[:12]
        # Bi-Temporalität (Zep/Graphiti-Lektion): Fakt-Gültigkeit getrennt
        # von der Commit-Zeit (die liefert die Git-Historie gratis).
        self.valid_from = valid_from or _now_iso()
        self.valid_to = valid_to  # None = aktuell gültig; gesetzt = invalidiert
        # V2#3: Confidence (Kosinus) der Auto-Vorschläge; None bei manuellen Links.
        self.confidence = confidence
        # V1#1: Provenance — welche Kante/Event diese Kante invalidiert hat.
        self.invalidated_by = invalidated_by

    def to_dict(self) -> dict:
        return {"id": self.id, "source": self.source, "target": self.target,
                "kind": self.kind, "pending": self.pending,
                "valid_from": self.valid_from, "valid_to": self.valid_to,
                "confidence": self.confidence,
                "invalidated_by": self.invalidated_by}


class Brain:
    """Das private Repo als Speicher. mode="git" synced, mode="local" nur FS."""

    def __init__(self, path: str, remote: str | None = None, mode: str = "local"):
        self.path = Path(path)
        self.remote = remote
        self.mode = mode

    # ---------- Git-Sync ----------

    def clone_if_missing(self) -> None:
        if self.path.exists() and (self.path / ".git").exists():
            return
        if not self.remote:
            raise ValueError("Kein remote angegeben und kein Clone vorhanden.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", self.remote, str(self.path)], check=True)

    def init(self, remote: str | None = None, commit: bool = True) -> None:
        """Erstellt ein frisches Brain-Repo am Pfad (Onboarding: `ig init`).

        Legt die Struktur (nodes/, edges.jsonl, vectors.jsonl, INDEX.md) an,
        `git init` + Branch main, optional ein origin-Remote, und committet den
        Startzustand. Idempotent: ein bereits existierendes Repo wird nicht
        überschrieben. Ohne Remote bleibt der erste Commit lokal (push=False).
        """
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "nodes").mkdir(parents=True, exist_ok=True)
        if not self.edges_file.exists():
            self.write_edges([])
        if not self.vectors_file.exists():
            self.write_vectors({})
        self.rebuild_index()
        if self.mode == "git" and not (self.path / ".git").exists():
            subprocess.run(["git", "-C", str(self.path), "init", "--quiet"], check=True)
            subprocess.run(["git", "-C", str(self.path), "symbolic-ref",
                            "HEAD", "refs/heads/main"], check=True)
            if remote:
                self.remote = remote
                subprocess.run(["git", "-C", str(self.path), "remote", "add",
                                "origin", remote], check=True)
        if commit:
            # Mit Remote → initialen Commit pushen; ohne → nur lokal committen.
            self.commit_and_push("init: Brain-Repo angelegt", push=bool(remote))

    def ensure_ready(self) -> None:
        """Stellt sicher, dass das Brain-Repo existiert (init oder clone).

        Wird am Anfang jedes Schreibpfads aufgerufen, damit `ig ingest` auf
        einer frischen Maschine ohne manuelles Setup sofort funktioniert.
        """
        if self.mode != "git":
            self.path.mkdir(parents=True, exist_ok=True)
            return
        if (self.path / ".git").exists():
            return
        if self.remote:
            self.clone_if_missing()
        else:
            self.init(remote=None, commit=False)

    def pull(self) -> None:
        if self.mode != "git":
            return
        # Ohne origin (frisch `ig init`-ed, lokal) ist pull ein No-op.
        has_origin = subprocess.run(
            ["git", "-C", str(self.path), "remote", "get-url", "origin"],
            capture_output=True).returncode == 0
        if not has_origin:
            return
        subprocess.run(["git", "-C", str(self.path), "pull", "--quiet",
                        "origin", "main"], check=True)

    def commit_and_push(self, message: str, push: bool = True) -> None:
        if self.mode != "git":
            return
        # Bot-Identität ist konfigurierbar (IG_BOT_NAME/IG_BOT_EMAIL); keine
        # fest verdrahtete persönliche Identität mehr.
        bot_name = os.environ.get("IG_BOT_NAME", "ideagraph-bot")
        bot_email = os.environ.get("IG_BOT_EMAIL", "bot@ideagraph.local")
        env_user = ["-c", f"user.name={bot_name}", "-c", f"user.email={bot_email}"]
        subprocess.run(["git", "-C", str(self.path), *env_user, "add", "-A"], check=True)
        diff = subprocess.run(["git", "-C", str(self.path), *env_user,
                               "diff", "--cached", "--quiet"], capture_output=True)
        if diff.returncode == 0:
            return  # nichts zu committen
        subprocess.run(["git", "-C", str(self.path), *env_user,
                        "commit", "--quiet", "-m", message], check=True)
        if not push:
            return
        # Nur pushen, wenn ein origin existiert (frisch `ig init`-ed ohne Remote
        # hat keinen — dann bleibt der erste Commit lokal).
        has_origin = subprocess.run(
            ["git", "-C", str(self.path), "remote", "get-url", "origin"],
            capture_output=True).returncode == 0
        if has_origin:
            subprocess.run(["git", "-C", str(self.path), "push", "--quiet",
                            "origin", "main"], check=True)

    # ---------- Nodes ----------

    def node_path(self, node_id: str) -> Path:
        return self.path / "nodes" / f"{node_id}.md"

    def merge_node(self, node: Node, source: str | None = None) -> None:
        """Duplikat-Ingest: bestehende Node behalten, Quelle protokollieren.

        tags/created bleiben unberührt; die neue source wird ins Frontmatter
        als `sources:`-Liste aufgenommen (ohne Duplikate).
        """
        sources = list(getattr(node, "sources", []) or [])
        if node.source not in sources:
            sources.insert(0, node.source)
        if source and source not in sources:
            sources.append(source)
        node.sources = sources
        self.write_node(node)

    def write_node(self, node: Node) -> None:
        nodes_dir = self.path / "nodes"
        nodes_dir.mkdir(parents=True, exist_ok=True)
        self.node_path(node.id).write_text(node.to_markdown(), encoding="utf-8")

    def promote_node(self, node_id: str) -> Node | None:
        """Dual-Buffer (V2#2): probation -> active nach erfolgreicher Dedup-Prüfung."""
        node = next((n for n in self.read_nodes() if n.id == node_id), None)
        if node is None:
            return None
        node.status = "active"
        self.write_node(node)
        return node

    def tombstone_node(self, node_id: str) -> Node | None:
        """Graceful Degradation (V2#2): Node als vergessen markieren (nie hart löschen)."""
        node = next((n for n in self.read_nodes() if n.id == node_id), None)
        if node is None:
            return None
        node.status = "tombstone"
        self.write_node(node)
        return node

    def read_nodes(self) -> list[Node]:
        nodes_dir = self.path / "nodes"
        if not nodes_dir.exists():
            return []
        out = []
        for p in sorted(nodes_dir.glob("*.md")):
            try:
                out.append(Node.from_markdown(p.read_text(encoding="utf-8")))
            except (ValueError, KeyError):
                continue  # kaputte Datei überspringen statt crashen
        return out

    # ---------- Embedding-Cache ----------

    @property
    def vectors_file(self) -> Path:
        return self.path / "vectors.jsonl"

    def read_vectors(self) -> dict[str, list[float]]:
        if not self.vectors_file.exists():
            return {}
        out: dict[str, list[float]] = {}
        for line in self.vectors_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                out[d["id"]] = d["vec"]
        return out

    def write_vectors(self, vectors: dict[str, list[float]]) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        with self.vectors_file.open("w", encoding="utf-8") as f:
            for nid, vec in sorted(vectors.items()):
                f.write(json.dumps({"id": nid, "vec": vec}) + "\n")

    def vectors_for(self, node_ids: set[str], embed_fn) -> dict[str, list[float]]:
        """Vektoren aus dem Cache, fehlende werden via embed_fn berechnet und gespeichert."""
        cached = self.read_vectors()
        dirty = False
        for nid in node_ids:
            if nid not in cached:
                node = next((n for n in self.read_nodes() if n.id == nid), None)
                if node is None:
                    continue
                cached[nid] = embed_fn(node.text)
                dirty = True
        if dirty:
            self.write_vectors(cached)
        return {nid: v for nid, v in cached.items() if nid in node_ids}

    # ---------- Edges ----------

    @property
    def edges_file(self) -> Path:
        return self.path / "edges.jsonl"

    def read_edges(self) -> list[Edge]:
        if not self.edges_file.exists():
            return []
        edges = []
        for line in self.edges_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                edges.append(Edge(d["source"], d["target"], d["kind"],
                                  d.get("pending", False), d["id"],
                                  valid_from=d.get("valid_from"),
                                  valid_to=d.get("valid_to"),
                                  confidence=d.get("confidence"),
                                  invalidated_by=d.get("invalidated_by")))
        return edges

    def write_edges(self, edges: list[Edge]) -> None:
        with self.edges_file.open("w", encoding="utf-8") as f:
            for e in edges:
                f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")

    def add_edge(self, edge: Edge) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        edges = self.read_edges()
        edges.append(edge)
        self.write_edges(edges)

    def invalidate_edge(self, edge_id: str, reason: str | None = None,
                        by_edge_id: str | None = None) -> Edge | None:
        """Kante invalidieren statt löschen (Zep-Lektion): valid_to wird gesetzt,
        die Kante bleibt mit voller Historie in der Datei. `by_edge_id` hält die
        Provenance, welche Kante/Event diese invalidiert hat (V1#1)."""
        edges = self.read_edges()
        edge = next((e for e in edges if e.id == edge_id), None)
        if edge is None or edge.valid_to is not None:
            return None
        edge.valid_to = _now_iso()
        if by_edge_id:
            edge.invalidated_by = by_edge_id
        self.write_edges(edges)
        return edge

    def resolve_edge(self, edge_id: str, accept: bool) -> Edge | None:
        edges = self.read_edges()
        edge = next((e for e in edges if e.id == edge_id and e.pending), None)
        if edge is None:
            return None
        if accept:
            edge.pending = False
            self.write_edges(edges)
            return edge
        edges.remove(edge)
        self.write_edges(edges)
        return edge

    # ---------- Graph-State fürs Frontend ----------

    def graph_state(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.read_nodes()],
            "edges": [e.to_dict() for e in self.read_edges()],
        }

    # ---------- Generiertes Inhaltsverzeichnis ----------

    def rebuild_index(self) -> None:
        lines = ["# Index", "", "| Idee | Quelle | Erstellt |", "|---|---|---|"]
        for n in self.read_nodes():
            title = n.text.replace("|", "\\|")[:60]
            lines.append(f"| [{title}](nodes/{n.id}.md) | {n.source} | {n.created} |")
        (self.path / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
