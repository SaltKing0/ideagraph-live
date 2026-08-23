"""FastAPI-Server auf Brain-Basis (privates Git-Repo als Speicher).

Env-Steuerung:
  IG_BRAIN_PATH   — Pfad zum Brain-Clone (default: ~/ideagraph-brain)
  IG_BRAIN_REMOTE — SSH/GitHub-URL (default: git@github.com:your-brain-repo.git)
  IG_BRAIN_MODE   — "git" (echtes Repo) oder "local" (nur FS, für Tests)
  IDEAGRAPH_EMBEDDER — "st" (sentence-transformers) oder "hash" (Demo/Tests)
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .brain import Brain
from .brain_engine import BrainEngine
from .embedder import get_embedder

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

app = FastAPI(title="IdeaGraph Live Engine")


def make_brain() -> Brain:
    return Brain(
        path=os.environ.get("IG_BRAIN_PATH", str(Path.home() / "ideagraph-brain")),
        remote=os.environ.get("IG_BRAIN_REMOTE", "git@github.com:your-brain-repo.git"),
        mode=os.environ.get("IG_BRAIN_MODE", "git"),
    )


def make_engine() -> BrainEngine:
    return BrainEngine(make_brain(), get_embedder(os.environ.get("IDEAGRAPH_EMBEDDER", "st")))


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict):
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


@app.get("/")
def index():
    return FileResponse(DOCS_DIR / "index.html")


@app.get("/app.js")
def app_js():
    return FileResponse(DOCS_DIR / "app.js")


@app.get("/review")
def review():
    return FileResponse(DOCS_DIR / "review.html")


@app.get("/review.js")
def review_js():
    return FileResponse(DOCS_DIR / "review.js")


@app.get("/api/graph")
def graph():
    return JSONResponse(make_brain().graph_state())


class IngestBody(BaseModel):
    text: str
    source: str = "human"
    tags: list[str] = []
    allow_duplicates: bool = False


@app.post("/api/ingest")
async def ingest(body: IngestBody):
    engine = make_engine()
    node, edges, is_dup = engine.ingest(body.text, body.source, body.tags,
                                        allow_duplicates=body.allow_duplicates)
    await manager.broadcast({
        "type": "ingested",
        "node": node.to_dict(),
        "edges": [e.to_dict() for e in edges],
        "duplicate": is_dup,
    })
    return {"node": node.to_dict(), "suggested": [e.to_dict() for e in edges],
            "duplicate": is_dup}


@app.post("/api/edge/{edge_id}/accept")
async def accept_edge(edge_id: str):
    edge = make_engine().resolve(edge_id, accept=True)
    if edge is None:
        return JSONResponse({"error": "edge nicht gefunden oder nicht pending"}, status_code=404)
    await manager.broadcast({"type": "edge_resolved", "edge": edge.to_dict(), "accepted": True})
    return edge.to_dict()


@app.post("/api/edge/{edge_id}/reject")
async def reject_edge(edge_id: str):
    edge = make_engine().resolve(edge_id, accept=False)
    if edge is None:
        return JSONResponse({"error": "edge nicht gefunden oder nicht pending"}, status_code=404)
    await manager.broadcast({"type": "edge_resolved", "edge": edge.to_dict(), "accepted": False})
    return {"rejected": edge_id}


class LinkBody(BaseModel):
    source: str
    target: str
    kind: str = "same_as"


@app.post("/api/edge")
async def link_edge(body: LinkBody):
    try:
        edge = make_engine().link(body.source, body.target, body.kind)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    await manager.broadcast({"type": "edge_linked", "edge": edge.to_dict()})
    return edge.to_dict()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
