"""API coverage for reversible decisions and live updates; uses an isolated brain."""

import pytest
from fastapi.testclient import TestClient

from ideagraph.brain import Brain, Edge, Node
from ideagraph.server import app


@pytest.fixture
def client_and_edge(tmp_path, monkeypatch):
    path = tmp_path / "brain"
    monkeypatch.setenv("IG_BRAIN_PATH", str(path))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "hash")
    brain = Brain(str(path))
    brain.write_node(Node(id="first", text="Erste Idee"))
    brain.write_node(Node(id="second", text="Zweite Idee"))
    edge = Edge(source="first", target="second", kind="ähnlich")
    brain.add_edge(edge)
    with TestClient(app) as client:
        yield client, edge


@pytest.mark.parametrize("action", ["accept", "reject"])
def test_saved_decision_can_be_undone_with_live_update(client_and_edge, action):
    client, edge = client_and_edge
    with client.websocket_connect("/ws") as ws:
        assert client.post(f"/api/edge/{edge.id}/{action}").status_code == 200
        assert ws.receive_json()["type"] == "edge_resolved"
        edges = client.get("/api/graph").json()["edges"]
        assert (edges == []) if action == "reject" else (edges[0]["pending"] is False)
        restored = client.post(f"/api/edge/{edge.id}/undo")
        assert restored.status_code == 200
        assert restored.json() == edge.to_dict()
        assert ws.receive_json() == {"type": "edge_restored", "edge": edge.to_dict()}
        assert client.get("/api/graph").json()["edges"] == [edge.to_dict()]
        assert client.post(f"/api/edge/{edge.id}/undo").status_code == 409


def test_unknown_undo_and_local_ui_routes(client_and_edge):
    client, _ = client_and_edge
    assert client.post("/api/edge/unknown/undo").status_code == 409
    for path, content_type in [("/", "text/html"), ("/app.js", "javascript"),
                               ("/review", "text/html"), ("/review.js", "javascript")]:
        response = client.get(path)
        assert response.status_code == 200
        assert content_type in response.headers["content-type"]
