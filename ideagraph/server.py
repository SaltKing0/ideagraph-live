"""FastAPI-Server auf Brain-Basis (privates Git-Repo als Speicher).

Env-Steuerung:
  IG_BRAIN_PATH   — Pfad zum Brain-Clone (default: ~/ideagraph-brain)
  IG_BRAIN_REMOTE — SSH/GitHub-URL (nur für `git clone` beim ersten
                    Einrichten; kein persönlicher Default, Bestandsklones
                    nutzen ihr eigenes origin)
  IG_BRAIN_MODE   — "git" (echtes Repo) oder "local" (nur FS, für Tests)
  IDEAGRAPH_EMBEDDER — "st" (sentence-transformers) oder "hash" (Demo/Tests)
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
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
        remote=os.environ.get("IG_BRAIN_REMOTE", "") or None,
        mode=os.environ.get("IG_BRAIN_MODE", "git"),
    )


# Audit #16: pro Request eine frische Engine zu bauen re-instantiiert das
# sentence-transformers-Modell pro Request (Sekunden CPU, Memory-Churn).
# Ein prozessweiter Cache teilt das Modell + den Vektor-Cache; die
# Schreibkonsistenz liefert der Brain-Instanz-Lock (alle RMW-Mutationen
# laufen unter brain._lock bzw. BRAIN_LOCK). Der Cache ist an
# (Brain-Pfad, Embedder) gekoppelt: ein geändertes Env (Tests, Multi-Brain-
# Setups) bekommt korrekt eine frische Engine statt der fremden Instanz.
_ENGINES: dict[tuple[str, str], BrainEngine] = {}


def make_engine() -> BrainEngine:
    brain_path = str(Path(os.environ.get("IG_BRAIN_PATH", str(Path.home() / "ideagraph-brain"))).expanduser())
    embedder_name = os.environ.get("IDEAGRAPH_EMBEDDER", "st")
    key = (brain_path, embedder_name)
    eng = _ENGINES.get(key)
    if eng is None:
        eng = BrainEngine(make_brain(), get_embedder(embedder_name))
        _ENGINES[key] = eng
    return eng


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


NO_CACHE = {"Cache-Control": "no-store"}


@app.get("/")
def index():
    return FileResponse(DOCS_DIR / "index.html", headers=NO_CACHE)


@app.get("/app.js")
def app_js():
    return FileResponse(DOCS_DIR / "app.js", headers=NO_CACHE)


@app.get("/review")
def review():
    return FileResponse(DOCS_DIR / "review.html", headers=NO_CACHE)


@app.get("/review.js")
def review_js():
    return FileResponse(DOCS_DIR / "review.js", headers=NO_CACHE)


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
    # Audit #16: git pull/push + Embedding-Inferenz sind Blocking-I/O — sie
    # laufen im Threadpool, nicht auf dem Event-Loop (sonst stallt ein
    # langsamer Ingest alle Requests und WS-Broadcasts).
    engine = make_engine()
    node, edges, is_dup = await run_in_threadpool(
        engine.ingest, body.text, body.source, body.tags,
        body.allow_duplicates)
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
    edge = await run_in_threadpool(make_engine().resolve, edge_id, True)
    if edge is None:
        return JSONResponse({"error": "edge not found or not pending"}, status_code=404)
    await manager.broadcast({"type": "edge_resolved", "edge": edge.to_dict(), "accepted": True})
    return edge.to_dict()


@app.post("/api/edge/{edge_id}/reject")
async def reject_edge(edge_id: str):
    edge = await run_in_threadpool(make_engine().resolve, edge_id, False)
    if edge is None:
        return JSONResponse({"error": "edge not found or not pending"}, status_code=404)
    await manager.broadcast({"type": "edge_resolved", "edge": edge.to_dict(), "accepted": False})
    return {"rejected": edge_id}


class LinkBody(BaseModel):
    source: str
    target: str
    kind: str = "same_as"


@app.post("/api/edge")
async def link_edge(body: LinkBody):
    def _link():
        try:
            return make_engine().link(body.source, body.target, body.kind), None
        except ValueError as exc:
            return None, str(exc)
    edge, err = await run_in_threadpool(_link)
    if err is not None or edge is None:
        return JSONResponse({"error": err or "link failed"}, status_code=400)
    await manager.broadcast({"type": "edge_linked", "edge": edge.to_dict()})
    return edge.to_dict()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            # Audit #29: nur WebSocketDisconnect zu fangen ließ Zombies zurück
            # (Binary-Frame → KeyError, TCP-Reset → RuntimeError) — die Socket
            # blieb forever in manager.active und wurde nie geschlossen.
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)
        try:
            await ws.close()
        except Exception:
            pass


@app.post("/api/edge/{edge_id}/undo")
async def undo_edge(edge_id: str):
    edge = await run_in_threadpool(make_engine().undo, edge_id)
    if edge is None:
        return JSONResponse({"error": "edge not found or already resolved"}, status_code=409)
    await manager.broadcast({"type": "edge_restored", "edge": edge.to_dict()})
    return edge.to_dict()
