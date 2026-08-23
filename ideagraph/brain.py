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
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Node:
    def __init__(self, text: str, id: str | None = None, created: str | None = None,
                 source: str = "human", tags: list[str] | None = None,
                 sources: list[str] | None = None):
        self.text = text
        self.id = id or uuid.uuid4().hex[:12]
        self.created = created or _now_iso()
        self.source = source
        self.tags = tags or []
        self.sources = sources or []

    def to_markdown(self) -> str:
        tags = "[" + ", ".join(self.tags) + "]" if self.tags else "[]"
        lines = [f"id: {self.id}", f"created: {self.created}",
                 f"source: {self.source}"]
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
                   source=meta.get("source", "human"), tags=tags, sources=sources)

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "created": self.created,
                "source": self.source, "tags": self.tags, "sources": self.sources}


class Edge:
    def __init__(self, source: str, target: str, kind: str,
                 pending: bool = True, id: str | None = None):
        self.source = source
        self.target = target
        self.kind = kind
        self.pending = pending
        self.id = id or uuid.uuid4().hex[:12]

    def to_dict(self) -> dict:
        return {"id": self.id, "source": self.source, "target": self.target,
                "kind": self.kind, "pending": self.pending}


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

    def pull(self) -> None:
        if self.mode != "git":
            return
        subprocess.run(["git", "-C", str(self.path), "pull", "--quiet",
                        "origin", "main"], check=True)

    def commit_and_push(self, message: str) -> None:
        if self.mode != "git":
            return
        env_user = ["-c", "user.name=ideagraph-bot", "-c", "user.email=bot@ideagraph.local"]
        subprocess.run(["git", "-C", str(self.path), *env_user, "add", "-A"], check=True)
        diff = subprocess.run(["git", "-C", str(self.path), *env_user,
                               "diff", "--cached", "--quiet"], capture_output=True)
        if diff.returncode == 0:
            return  # nichts zu committen
        subprocess.run(["git", "-C", str(self.path), *env_user,
                        "commit", "--quiet", "-m", message], check=True)
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
                                  d.get("pending", False), d["id"]))
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
