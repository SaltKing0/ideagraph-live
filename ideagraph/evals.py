"""Eval-Layer für die Engine (Roadmap V2#4).

End-State-Verification statt Transcripts: Jede Eval-Aufgabe beschreibt einen
Ingest-Ablauf + ein ORACLE über den finalen Brain-State (existiert der Node,
sind die Edges gesetzt, wurde das Duplikat gemergt?). Deterministische Checker
laufen gegen den tatsächlichen Brain-Zustand — kein Blick auf Zwischenschritte.

Zwei Stufen (Tiered Gates):
  - GOLDEN_SET: Regression auf jedem Engine-Wandel. Diese Fälle MÜSSEN auf dem
    aktuellen Stand grün sein — sie frieren das Ist-Verhalten als Baseline ein.
  - ROADMAP_CASES: Dokumentieren gewünschtes Zukunfts-Verhalten aus der Roadmap
    (Confidence-Bänder, Intent-Edges, Kontradiktionen). Sie sind als Spezifikation
    registriert und werden grün, sobald das Feature implementiert ist — das macht
    Fortschritt messbar, ohne die Baseline zu brechen.

pass^k: run_eval(... k=...) führt dieselbe Aufgabe k-mal gegen eine frische
Brain aus und verlangt, dass ALLE Läufe bestehen (Schutz vor Flakiness).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .brain import Brain, Node
from .brain_engine import BrainEngine
from .retrieval import retrieve


# ---------------------------------------------------------------------------
# Oracle / Aufgaben
# ---------------------------------------------------------------------------

@dataclass
class EdgeExpectation:
    """Eine erwartete Kante, textbasiert (Source-/Target-NODE-INHALT).

    kind="*" bedeutet: irgendeine aktive Kante zwischen den beiden Nodes genügt
    (robust gegen exakte Kind-Namen, wenn es nur um "verbunden sein" geht).
    pending/min_confidence sind optional und prüfen das Confidence-Band (V2#3).
    """
    source: str
    target: str
    kind: str
    pending: bool | None = None          # falls gesetzt: Edge muss diesen pending-Wert haben
    min_confidence: float | None = None  # falls gesetzt: Edge.confidence >= dieser Wert


@dataclass
class RetrievalExpectation:
    """Eine Retrieval-Erwartung (Hybrid dense+BM25): Query muss passende Nodes liefern."""
    query: str
    top: int = 5
    includes: list[str] = field(default_factory=list)   # Node-Texte, die in den top-`top` vorkommen müssen
    excludes: list[str] = field(default_factory=list)   # Node-Texte, die NICHT vorkommen dürfen


@dataclass
class EvalOracle:
    """Soll-Zustand des Brains nach der Ingest-Sequenz."""
    node_count: int | None = None
    nodes_present: list[str] = field(default_factory=list)
    node_absent: list[str] = field(default_factory=list)
    # (Text, erforderliche sources): Node mit diesem Text muss all diese sources haben.
    duplicate_merged: list[tuple[str, list[str]]] = field(default_factory=list)
    edges: list[EdgeExpectation] = field(default_factory=list)
    no_edge: list[EdgeExpectation] = field(default_factory=list)
    retrieval: list[RetrievalExpectation] = field(default_factory=list)


@dataclass
class EvalTask:
    id: str
    name: str
    ingests: list[tuple[str, dict]]  # (text, kwargs) — Reihenfolge ist Teil des Szenarios
    oracle: EvalOracle
    # Optionale Aktionen NACH den Ingests (z. B. manuelle same_as-Links).
    actions: list[Callable[[BrainEngine], None]] = field(default_factory=list)


@dataclass
class EvalResult:
    task_id: str
    name: str
    passed: bool
    failures: list[str]
    runs: int


# ---------------------------------------------------------------------------
# End-State-Checker
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def find_node_by_text(brain: Brain, text: str) -> Node | None:
    """Node, dessen Inhalt (normalisiert) mit `text` beginnt, sonst None.

    Starts-with statt exakt: Memory Evolution hängt auto-akzeptierten
    "ähnlich"-Kanten einen "[evolved …]" Querverweis ans Ende — der ursprüngliche
    Text bleibt Präfix, und die Zuordnung soll dennoch greifen.
    """
    target = _norm(text)
    for n in brain.read_nodes():
        if _norm(n.text).startswith(target):
            return n
    return None


def verify_end_state(brain: Brain, oracle: EvalOracle) -> list[str]:
    """Prüft den finalen Brain-State gegen das Oracle. Liefert alle Fehler ([] = grün)."""
    failures: list[str] = []
    nodes = brain.read_nodes()
    edges = brain.read_edges()

    if oracle.node_count is not None and len(nodes) != oracle.node_count:
        failures.append(f"node_count: expected {oracle.node_count}, got {len(nodes)}")

    for text in oracle.nodes_present:
        if find_node_by_text(brain, text) is None:
            failures.append(f"node missing: {text!r}")

    for text in oracle.node_absent:
        if find_node_by_text(brain, text) is not None:
            failures.append(f"node should be absent: {text!r}")

    for text, req_sources in oracle.duplicate_merged:
        n = find_node_by_text(brain, text)
        if n is None:
            failures.append(f"dup node missing: {text!r}")
        else:
            for s in req_sources:
                if s not in n.sources:
                    failures.append(f"node {text!r} missing source {s!r} (got {n.sources})")

    for eexp in oracle.edges:
        s = find_node_by_text(brain, eexp.source)
        t = find_node_by_text(brain, eexp.target)
        if s is None or t is None:
            failures.append(f"edge endpoint missing: {eexp.source!r}->{eexp.target!r}")
            continue
        # Richtungsagnostisch: Auto-Edges zeigen vom neuesten zum älteren Node,
        # deshalb ist die Richtung für "verbunden sein" egal.
        active = [
            e for e in edges
            if e.valid_to is None
            and ((e.source == s.id and e.target == t.id) or (e.source == t.id and e.target == s.id))
        ]
        if eexp.kind != "*":
            kind_match = [e for e in active if e.kind == eexp.kind]
        else:
            kind_match = active
        if not kind_match:
            failures.append(f"edge missing: {eexp.source!r} --[{eexp.kind}]--> {eexp.target!r}")
            continue
        if eexp.pending is not None and not any(e.pending == eexp.pending for e in kind_match):
            failures.append(
                f"edge {eexp.source!r}->{eexp.target!r}: expected pending={eexp.pending}, "
                f"got {[e.pending for e in kind_match]}"
            )
        if eexp.min_confidence is not None and not any(
            (e.confidence or 0.0) >= eexp.min_confidence for e in kind_match
        ):
            failures.append(
                f"edge {eexp.source!r}->{eexp.target!r}: expected confidence>={eexp.min_confidence}, "
                f"got {[e.confidence for e in kind_match]}"
            )

    for eexp in oracle.no_edge:
        s = find_node_by_text(brain, eexp.source)
        t = find_node_by_text(brain, eexp.target)
        if s and t and any(
            e.source == s.id and e.target == t.id or e.source == t.id and e.target == s.id
            for e in edges
        ):
            failures.append(f"unexpected edge: {eexp.source!r} --[{eexp.kind}]--> {eexp.target!r}")

    return failures


def verify_retrieval(engine: BrainEngine, expectations: list[RetrievalExpectation]) -> list[str]:
    """Prüft Hybrid-Retrieval: Query muss erwartete Nodes in den top-k liefern (bzw. ausschließen)."""
    failures: list[str] = []
    id2node = {n.id: n for n in engine.brain.read_nodes()}
    for exp in expectations:
        hits = retrieve(engine, exp.query, k=exp.top)
        hit_texts = [_norm(id2node[nid].text) for nid, _ in hits if nid in id2node]
        for want in exp.includes:
            if not any(_norm(want) in t or t.startswith(_norm(want)) for t in hit_texts):
                failures.append(f"retrieval '{exp.query}' should hit {want!r} in top-{exp.top}")
        for avoid in exp.excludes:
            if any(_norm(avoid) in t or t.startswith(_norm(avoid)) for t in hit_texts):
                failures.append(f"retrieval '{exp.query}' should NOT hit {avoid!r} in top-{exp.top}")
    return failures


# ---------------------------------------------------------------------------
# Runner (pass^k)
# ---------------------------------------------------------------------------

EngineFactory = Callable[[], BrainEngine]


def run_eval(task: EvalTask, engine_factory: EngineFactory, k: int = 1) -> EvalResult:
    """Führt die Aufgabe k-mal gegen eine frische Brain aus; alle Läufe müssen grün sein."""
    for run in range(1, k + 1):
        engine = engine_factory()
        for text, kwargs in task.ingests:
            engine.ingest(text, **kwargs)
        for action in task.actions:
            action(engine)
        failures = verify_end_state(engine.brain, task.oracle)
        failures += verify_retrieval(engine, task.oracle.retrieval)
        if failures:
            return EvalResult(task.id, task.name, False, failures, run)
    return EvalResult(task.id, task.name, True, [], k)


def run_tasks(tasks: list[EvalTask], engine_factory: EngineFactory, k: int = 1) -> list[EvalResult]:
    return [run_eval(t, engine_factory, k) for t in tasks]


def report(results: list[EvalResult]) -> tuple[int, list[EvalResult]]:
    """Liefert (Anzahl grün, alle) — nützlich für CLI/Logging."""
    failed = [r for r in results if not r.passed]
    return len(results) - len(failed), failed


# ---------------------------------------------------------------------------
# Golden-Set — Regression auf jedem Engine-Wandel (MUSS grün sein)
# ---------------------------------------------------------------------------

def _link_same_as(source_text: str, target_text: str) -> Callable[[BrainEngine], None]:
    def action(engine: BrainEngine) -> None:
        s = find_node_by_text(engine.brain, source_text)
        t = find_node_by_text(engine.brain, target_text)
        if s and t:
            engine.link(s.id, t.id, "same_as")
    return action


GOLDEN_SET: list[EvalTask] = [
    EvalTask(
        id="dup-exact",
        name="exakter Duplikat wird gemergt (sources kumuliert)",
        ingests=[
            ("Katzen jagen Maeuse nachts", {"source": "agent/test"}),
            ("Katzen jagen Maeuse nachts", {"source": "human"}),
        ],
        oracle=EvalOracle(
            node_count=1,
            duplicate_merged=[("Katzen jagen Maeuse nachts", ["agent/test", "human"])],
        ),
    ),
    EvalTask(
        id="dup-case-whitespace",
        name="Duplikat unabhängig von Groß-/Kleinschreibung + Whitespace",
        ingests=[
            ("Katzen jagen Maeuse nachts", {"source": "a"}),
            ("  katzen JAGEN maeuse   NACHTS ", {"source": "b"}),
        ],
        oracle=EvalOracle(node_count=1, duplicate_merged=[("katzen jagen maeuse nachts", ["a", "b"])]),
    ),
    EvalTask(
        id="dup-disabled",
        name="allow_duplicates=True legt zweiten Node an",
        ingests=[
            ("Katzen jagen Maeuse nachts", {}),
            ("Katzen jagen Maeuse nachts", {"allow_duplicates": True}),
        ],
        oracle=EvalOracle(node_count=2),
    ),
    EvalTask(
        id="no-false-positive",
        name="unverwandte Texte werden nicht dedupliziert",
        ingests=[
            ("Katzen jagen Maeuse nachts", {}),
            ("Rust Compiler borrow checker lifetime Regeln", {}),
        ],
        oracle=EvalOracle(node_count=2, nodes_present=[
            "Katzen jagen Maeuse nachts",
            "Rust Compiler borrow checker lifetime Regeln",
        ]),
    ),
    EvalTask(
        id="edge-similar",
        name="ähnliche Nodes werden über eine Kante verbunden (pending <0.95)",
        ingests=[
            ("katze hund tier futter", {}),
            ("katze hund tier spiel", {}),
        ],
        oracle=EvalOracle(
            node_count=2,
            edges=[EdgeExpectation("katze hund tier futter", "katze hund tier spiel", "*", pending=True)],
        ),
    ),
    EvalTask(
        id="conf-auto-accept",
        name="V2: Confidence >=0.95 → Edge auto-akzeptiert (pending=False)",
        ingests=[
            ("x x x x x y y y y y z z z z z", {}),
            ("x x x x x y y y y y z z z z w", {"allow_duplicates": True}),
        ],
        oracle=EvalOracle(
            node_count=2,
            edges=[EdgeExpectation(
                "x x x x x y y y y y z z z z z",
                "x x x x x y y y y y z z z z w",
                "*", pending=False, min_confidence=0.95,
            )],
        ),
    ),
    EvalTask(
        id="edge-no-false-link",
        name="unverwandte Nodes werden NICHT verbunden",
        ingests=[
            ("katze hund tier futter", {}),
            ("quantenmechanik wellenfunktion schroedinger", {}),
        ],
        oracle=EvalOracle(
            node_count=2,
            no_edge=[EdgeExpectation("katze hund tier futter", "quantenmechanik wellenfunktion schroedinger", "*")],
        ),
    ),
    EvalTask(
        id="retrieval-hybrid",
        name="V2: Hybrid-Retrieval findet passende Node, nicht unverwandte",
        ingests=[
            ("katze hund tier futter", {}),
            ("quantenmechanik wellenfunktion schroedinger", {}),
        ],
        oracle=EvalOracle(
            node_count=2,
            retrieval=[RetrievalExpectation(
                query="katze futter",
                top=1,
                includes=["katze hund tier futter"],
                excludes=["quantenmechanik wellenfunktion schroedinger"],
            )],
        ),
    ),
    EvalTask(
        id="taxonomy-procedural",
        name="prozeduraler Node trägt type=procedural",
        ingests=[
            ("Wie ingestiere ich Research: ig ingest ...", {"ntype": "procedural"}),
        ],
        oracle=EvalOracle(node_count=1, nodes_present=["Wie ingestiere ich Research: ig ingest ..."]),
    ),
    EvalTask(
        id="same-as-multilingual",
        name="mehrsprachiges Paar via manuellem same_as-Link verbunden",
        ingests=[
            ("Katzen jagen Maeuse", {}),
            ("Cats hunt mice", {"allow_duplicates": True}),
        ],
        actions=[_link_same_as("Katzen jagen Maeuse", "Cats hunt mice")],
        oracle=EvalOracle(
            node_count=2,
            edges=[EdgeExpectation("Katzen jagen Maeuse", "Cats hunt mice", "same_as")],
        ),
    ),
]


# ---------------------------------------------------------------------------
# Roadmap-Fälle — gewünschtes Zukunfts-Verhalten (wird grün, sobald implementiert)
# ---------------------------------------------------------------------------

ROADMAP_CASES: list[EvalTask] = [
    EvalTask(
        id="roadmap-contradiction",
        name="V2: widersprüchliche Aussagen → 'kontradiktorisch'-Edge auto-erkannt",
        ingests=[
            ("Die Erde ist eine Scheibe", {}),
            ("Die Erde ist eine Kugel", {}),
        ],
        oracle=EvalOracle(
            node_count=2,
            edges=[EdgeExpectation("Die Erde ist eine Scheibe", "Die Erde ist eine Kugel", "kontradiktorisch")],
        ),
    ),
    EvalTask(
        id="roadmap-intent-supersedes",
        name="V2: neuere Aussage überschreibt ältere → 'supersedes'-Edge",
        ingests=[
            ("API v1 wird verwendet", {}),
            ("API v2 ersetzt v1", {}),
        ],
        oracle=EvalOracle(
            node_count=2,
            edges=[EdgeExpectation("API v1 wird verwendet", "API v2 ersetzt v1", "supersedes")],
        ),
    ),
]

