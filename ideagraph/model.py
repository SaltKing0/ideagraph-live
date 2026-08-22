"""Kern-Datenmodell: Nodes (Ideen) und getypte Edges.

Edges tragen einen Typ: "ähnlich", "kontradiktorisch", "erweitert".
Pending-Edges sind Vorschläge des Wachstums-Loops und warten auf
Human-in-the-loop Entscheidung (akzeptieren/verwerfen).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict

EDGE_TYPES = ("ähnlich", "kontradiktorisch", "erweitert")


def _now() -> float:
    return time.time()


@dataclass
class Node:
    text: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        return cls(text=d["text"], id=d["id"], created=d.get("created", 0.0))


@dataclass
class Edge:
    source: str          # Node-ID (neue Idee)
    target: str          # Node-ID (bestehende Idee)
    kind: str            # einer aus EDGE_TYPES
    pending: bool = True  # Vorschlag bis akzeptiert/verworfen
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Edge":
        return cls(
            source=d["source"],
            target=d["target"],
            kind=d["kind"],
            pending=d.get("pending", False),
            id=d["id"],
            created=d.get("created", 0.0),
        )
