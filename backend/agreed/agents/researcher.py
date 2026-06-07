"""Researcher agent — gathers facts via Exa during the prep phase (step 2.5).

Falls back to deterministic stub findings when no EXA_API_KEY is set so the prep
phase still produces a brief offline.
"""

from __future__ import annotations

from ..config import get_settings
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
        return {"query": query, "source": "stub", "findings": _stub(query)}


def _stub(query: str) -> list[dict]:
    return [
        {
            "title": "Market benchmark",
            "url": "https://example.com/benchmarks",
            "snippet": (
                f"Typical custom software platform contracts in this segment settle around "
                f"$70-78k with 12-18 week delivery and net30-net60 terms. (stub for: {query})"
            ),
        },
        {
            "title": "Negotiation leverage note",
            "url": "https://example.com/leverage",
            "snippet": "Sellers commonly hold firm on delivery timelines; buyers gain by trading payment-term flexibility for price.",
        },
    ]
