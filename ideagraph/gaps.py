"""Coverage- und Gap-Analyse über den Brain.

Klassifiziert jeden Node anhand einer Themen-Taxonomie (Bereich → Schlüsselwörter),
zählt die Abdeckung pro Bereich und identifiziert unterbesetzte Bereiche (Gaps).
Das steuert gezielte Forschung statt breiter Recherche.

Die Taxonomie ist generisch und über eine JSON-Datei austauschbar
(Format: {"Bereich": ["keyword", ...]}); DEFAULT_TAXONOMY ist ein sinnvoller
LLM/Agent-Default. Es wird nichts am Brain verändert (read-only).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .brain import Brain

# Standard-Taxonomie (LLM/Agent-Forschung) — generisch, keine persönlichen Daten.
DEFAULT_TAXONOMY: dict[str, list[str]] = {
    "Agent-Harness & Orchestrierung": [
        "harness", "orchestrierung", "agent-runtime", "supervisor", "handoff",
        "loop-kontrolle", "startup", "kontext-injektion", "resilienz",
        "circuit-breaker", "durable", "plan-and-execute", "agent-loop",
        "workflow", "subagent", "fanout", "delegation",
    ],
    "Coding-Agents & Code": [
        "code", "programmier", "coding", "software", "repo", "debug",
        "test-generierung", "code-review", "refactor", "swe-bench", "human-eval",
        "legacy", "api-generierung", "sql",
    ],
    "Multi-Agent-Systeme": [
        "multi-agent", "verhandlung", "auktion", "konsens", "voting",
        "kooperation", "konkurrenz", "spieltheorie", "mechanism-design",
        "incentive", "marktplatz", "interoperabilitaet", "blackboard",
        "agenten-routing", "schwarm", "peer-to-peer",
    ],
    "LLM-Architektur & Interna": [
        "attention", "transformer", "token", "embedding", "kv-cache", "position",
        "rope", "mamba", "ssm", "mixture", "moe", "architektur", "logits",
        "softmax", "layernorm", "tokenisierung", "bpe", "neuron",
    ],
    "Training & Alignment": [
        "rlhf", "dpo", "grpo", "ppo", "alignment", "fine-tuning", "finetuning",
        "lora", "peft", "qlora", "sft", "reward", "preference", "synthetic",
        "curriculum", "gradient", "loss", "optimizer", "adamw", "training",
    ],
    "Evals & Benchmarks": [
        "eval", "benchmark", "metrik", "leaderboard", "mmlu", "gsm8k", "judge",
        "kontamination", "golden", "oracle", "pass@k", "halluzination-messung",
        "test", "verifikation",
    ],
    "Retrieval & RAG": [
        "retrieval", "rag", "rerank", "bm25", "dense", "vector",
        "embedding-search", "chunk", "index", "graph-rag", "hybrid",
        "semantische-suche", "cross-encoder", "late-chunking",
    ],
    "Memory & Kontext": [
        "memory", "gedaechtnis", "kontext", "working-memory", "episodic",
        "context-engineering", "token-budget", "context-window", "scratchpad",
        "langzeit", "hierarchisches", "summarization", "kontext-kompression",
    ],
    "Serving & Inferenz": [
        "serving", "inferenz", "vllm", "batching", "prefill", "decode",
        "throughput", "latenz", "quantisierung", "gpu", "inference",
        "speculative", "disaggregated", "ttft", "pagedattention",
    ],
    "Sicherheit & Governance": [
        "sicherheit", "security", "jailbreak", "injection", "sandbox",
        "governance", "privacy", "datenschutz", "ethik", "regulierung", "audit",
        "compliance", "exfiltration", "autorisierung", "trust", "verantwortung",
    ],
    "Multimodal": [
        "multimodal", "vision", "bild", "audio", "speech", "tts", "video",
        "clip", "image", "sprach-synthese", "geste", "cross-modal",
        "text-to-image",
    ],
    "Konversations-KI": [
        "konversation", "dialog", "chatbot", "persona", "intent", "slot",
        "multi-turn", "chat", "gespraech", "engagement", "turn-qualitaet",
        "empathie",
    ],
    "Interpretability & Mechanistik": [
        "interpretab", "mechanistic", "sae", "sparse autoencoder", "activation",
        "circuit", "logit-lens", "probing", "attribution", "causal", "ablation",
        "steering", "transparenz", "erklaer",
    ],
    "Anwendungen": [
        "industr", "fertigung", "medizin", "biologie", "chemie", "physik",
        "bildung", "tutor", "lern", "content", "marketing", "journalismus",
        "recht", "finanz", "gesundheit", "wissenschaft", "astronomie", "ocean",
        "klima",
    ],
    "Oekonomie & Gesellschaft": [
        "oekonomie", "kosten", "open-source", "closed", "arbeitsmarkt", "umwelt",
        "gesellschaft", "wirtschaft", "markt", "lizenz", "urheber",
    ],
}


def normalize(text: str) -> str:
    """Kleinschreibung + Umlaut-Normalisierung (ä→ae etc.)."""
    s = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return s


def _node_text(node: Any) -> str:
    """Body eines Nodes ohne Frontmatter."""
    t = getattr(node, "text", "") or ""
    parts = t.split("---")
    return (parts[2] if len(parts) >= 3 else t).strip()


@dataclass
class AreaStat:
    name: str
    count: int = 0
    examples: list[dict] = field(default_factory=list)


@dataclass
class CoverageResult:
    total: int
    areas: list[AreaStat]  # sortiert nach count absteigend
    unclassified: int
    taxonomy: dict[str, list[str]]


def analyze_coverage(brain: Brain, taxonomy: dict[str, list[str]] | None = None) -> CoverageResult:
    """Klassifiziert alle Nodes über die Taxonomie und zählt Abdeckung pro Bereich.

    Ein Node kann mehreren Bereichen angehören (Schlüsselwort-Overlap).
    Read-only — verändert den Brain nicht.
    """
    tax = taxonomy or DEFAULT_TAXONOMY
    count: Counter = Counter()
    examples: dict[str, list] = defaultdict(list)
    nodes = brain.read_nodes()
    unclassified = 0
    for node in nodes:
        b = normalize(_node_text(node))
        matched = [area for area, kws in tax.items() if any(k in b for k in kws)]
        if not matched:
            unclassified += 1
        for m in matched:
            count[m] += 1
            if len(examples[m]) < 5:
                examples[m].append({"id": node.id, "text": _node_text(node)[:72]})
    areas = [AreaStat(name=a, count=count[a], examples=examples[a]) for a in tax]
    areas.sort(key=lambda s: s.count, reverse=True)
    return CoverageResult(total=len(nodes), areas=areas, unclassified=unclassified, taxonomy=tax)


def find_gaps(coverage: CoverageResult, threshold: int) -> list[AreaStat]:
    """Bereiche unterhalb der Schwelle, aufsteigend nach Abdeckung (dünnste zuerst)."""
    return [a for a in sorted(coverage.areas, key=lambda s: s.count) if a.count < threshold]


def render(coverage: CoverageResult, threshold: int) -> str:
    """Textueller Coverage-/Gap-Report."""
    lines = [
        f"Coverage ({coverage.total} Nodes, {len(coverage.areas)} Bereiche):",
        f"{'Nodes':>5}  {'Bereich':<40}  Abdeckung",
        "-----  " + "-" * 40 + "  ---------",
    ]
    maxc = max((a.count for a in coverage.areas), default=1)
    for a in coverage.areas:
        bar = "#" * int(a.count / maxc * 30)
        gap = "  ← GAP" if a.count < threshold else ""
        lines.append(f"{a.count:>5}  {a.name:<40}  {bar}{gap}")
    lines.append(f"{coverage.unclassified:>5}  {'UNKLASSIFIZIERT':<40}")
    gaps = find_gaps(coverage, threshold)
    if gaps:
        lines.append("")
        lines.append(f"GAPS (< {threshold} Nodes) — nächste Forschungsziele (dünnste zuerst):")
        for a in gaps:
            lines.append(f"  {a.count:>3}  {a.name}")
    return "\n".join(lines)


def load_taxonomy(path: str) -> dict[str, list[str]]:
    """Lädt eine Taxonomie aus einer JSON-Datei ({"Bereich": ["kw", ...]})."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not all(isinstance(v, list) for v in data.values()):
        raise ValueError("Taxonomie muss JSON-Objekt sein: {\"Bereich\": [\"kw\", ...]}")
    return data
