"""Researcher agent — gathers facts via Exa during the prep phase (step 2.5).

Falls back to deterministic stub findings when no EXA_API_KEY is set so the prep
phase still produces a brief offline.
"""

from __future__ import annotations

from ..config import get_settings
from ..llm import chat_json
from ..observability import op
from .base import Agent


class ResearcherAgent(Agent):
    role = "researcher"

    @op(name="researcher.research", kind="tool")
    def research(self, query: str, *, num_results: int = 4) -> dict:
        s = get_settings()
        if s.has_exa:
            try:
                from exa_py import Exa  # type: ignore

                exa = Exa(s.exa_api_key)
                res = exa.search_and_contents(query, num_results=num_results, text=True)
                findings = [
                    {"title": r.title, "url": r.url, "snippet": (r.text or "")[:300]}
                    for r in res.results
                ]
                return {"query": query, "source": "exa", "findings": findings}
            except Exception as exc:
                return {"query": query, "source": "exa-error", "error": str(exc), "findings": _stub(query)}
        findings = _llm_findings(query, num_results=num_results)
        if findings:
            return {"query": query, "source": "llm", "findings": findings}
        return {"query": query, "source": "fallback", "findings": _stub(query)}


def _llm_findings(query: str, *, num_results: int) -> list[dict]:
    data = chat_json(
        "You create concise prep notes for an AI negotiation agent. Return JSON only.",
        (
            f"Negotiation context: {query}\n"
            f"Generate {num_results} practical, non-fabricated preparation findings. "
            "Do not cite URLs unless you truly know them. Use this JSON shape: "
            '{"findings":[{"title":"short label","snippet":"one useful sentence"}]}'
        ),
        max_tokens=500,
        temperature=0.5,
    )
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        return []
    findings: list[dict] = []
    for item in data["findings"][:num_results]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "Prep note").strip()[:80]
        snippet = str(item.get("snippet") or "").strip()[:300]
        if snippet:
            findings.append({"title": title, "snippet": snippet})
    return findings


def _stub(query: str) -> list[dict]:
    """Generic, non-fabricated prep notes used only when no LLM/Exa is available.

    Deliberately avoids inventing specific prices or benchmarks — it offers
    sound, goal-agnostic negotiation tactics instead.
    """
    return [
        {
            "title": "Anchor on your targets",
            "snippet": (
                "Open near your stated target and let the other side reveal their priorities "
                "before conceding — don't move off your walk-away."
            ),
        },
        {
            "title": "Trade across terms",
            "snippet": (
                "Find trades where each side gives on a lower-priority term to win a higher-priority "
                "one; that's where mutual gains come from."
            ),
        },
    ]
