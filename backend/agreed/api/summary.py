"""Plain-language trace summary.

Trace visibility is a product feature, not a debug tool. This turns the raw spans
into a human-readable, expandable narrative for the UI, and links to the hosted
Weave dashboard when configured.
"""

from __future__ import annotations

from ..observability import get_spans, weave_trace_url

_KIND_VERB = {
    "agent": "agent step",
    "llm": "model call",
    "tool": "tool call",
    "a2a": "agent-to-agent message",
    "graph": "orchestration",
    "eval": "evaluation",
    "event": "event",
}


def summarize_trace(trace_id: str) -> dict:
    spans = get_spans(trace_id)
    steps = []
    counts: dict[str, int] = {}
    for sp in spans:
        kind = sp["kind"]
        counts[kind] = counts.get(kind, 0) + 1
        steps.append(
            {
                "id": sp["id"],
                "label": _plain_label(sp),
                "kind": kind,
                "category": _KIND_VERB.get(kind, kind),
                "duration_ms": sp["duration_ms"],
                "error": sp["error"],
                "why": sp["output"] if isinstance(sp["output"], str) else None,
                "detail": sp,  # full reasoning, expandable in the UI
            }
        )
    return {
        "trace_id": trace_id,
        "span_count": len(spans),
        "by_kind": counts,
        "weave_url": weave_trace_url(),
        "steps": steps,
    }


def _plain_label(sp: dict) -> str:
    name = sp["name"]
    attrs = sp.get("attributes", {})
    if name == "negotiator.act":
        return "A negotiator decided its next move"
    if name.startswith("llm."):
        return "The agent called a language model"
    if name == "moderator.propose_settlement":
        return "The moderator searched for the optimal settlement"
    if name == "moderator.candidate_frontier":
        return "The moderator built the Pareto frontier of candidate deals"
    if name == "critic.evaluate":
        return "The critic scored a proposal against both utility functions"
    if name == "researcher.research":
        return "The researcher gathered market context"
    if name == "sandbox.start":
        return f"Started a sandbox for {attrs.get('agent', 'an agent')} ({attrs.get('backend', 'local')})"
    if name.startswith("self_improve"):
        return "The self-improvement agent analyzed and optimized strategy"
    if name == "store.put":
        return "Saved a record (scoped to the user)"
    if name == "a2a.send":
        return "An A2A protocol message was sent"
    return name.replace(".", " · ")
