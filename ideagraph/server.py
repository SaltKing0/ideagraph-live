"""FastAPI-Server: REST + WebSocket-Live-Update, kein Build-Step."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .store import Store
from .embedder import get_embedder, HashEmbedder
from .engine import Engine

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

app = FastAPI(title="IdeaGraph Live Engine")
store = Store()
_embedder: HashEmbedder | None = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        # Env-Steuerung: IDEAGRAPH_EMBEDDER=hash für den Test-/Demo-Modus
        import os
        _embedder = get_embedder(os.environ.get("IDEAGRAPH_EMBEDDER", "st"))
    return _embedder


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


@app.get("/api/graph")
def graph():
    return JSONResponse(store.graph_state())


class IngestBody(BaseModel):
    text: str


@app.post("/api/ingest")
async def ingest(body: IngestBody):
    engine = Engine(store, _get_embedder())
    node, edges = engine.ingest(body.text)
    await manager.broadcast({
        "type": "ingested",
        "node": node.to_dict(),
        "edges": [e.to_dict() for e in edges],
    })
    return {"node": node.to_dict(), "suggested": [e.to_dict() for e in edges]}


@app.post("/api/edge/{edge_id}/accept")
async def accept_edge(edge_id: str):
    edge = store.resolve_edge(edge_id, accept=True)
    if edge is None:
        return JSONResponse({"error": "edge nicht gefunden oder nicht pending"}, status_code=404)
    await manager.broadcast({"type": "edge_resolved", "edge": edge.to_dict(), "accepted": True})
    return edge.to_dict()


@app.post("/api/edge/{edge_id}/reject")
async def reject_edge(edge_id: str):
    edge = store.resolve_edge(edge_id, accept=False)
    if edge is None:
        return JSONResponse({"error": "edge nicht gefunden oder nicht pending"}, status_code=404)
    await manager.broadcast({"type": "edge_resolved", "edge": edge.to_dict(), "accepted": False})
    return {"rejected": edge_id}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
