"""Pluggable LLM client.

Three backends, auto-selected:
  - "openai"    : OpenAI Chat Completions
  - "wandb"     : W&B Inference (OpenAI-compatible endpoint) — counts as sponsor usage
  - "heuristic" : no network; callers fall back to a deterministic strategy engine

Every call is Weave-traced. When no API backend is available, `chat_json` returns
None and agents use their built-in heuristic policy so the demo always runs.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .config import get_settings
from .observability import op

_client = None
_client_backend: str | None = None


def _build_client():
    """Create an OpenAI-compatible client for the resolved backend, or None."""
    global _client, _client_backend
    s = get_settings()
    backend = s.resolved_llm_backend
    if backend == "heuristic":
        return None, "heuristic"

    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        return None, "heuristic"

    try:
        if backend == "wandb" and s.has_wandb:
            client = OpenAI(api_key=s.wandb_api_key, base_url=s.wandb_inference_base_url)
            return client, "wandb"
        if backend == "openai" and s.has_openai:
            client = OpenAI(api_key=s.openai_api_key)
            return client, "openai"
        # Fall through: try whichever key exists
        if s.has_openai:
            return OpenAI(api_key=s.openai_api_key), "openai"
    except Exception:
        return None, "heuristic"
    return None, "heuristic"


def get_client():
    global _client, _client_backend
    if _client_backend is None:
        _client, _client_backend = _build_client()
    return _client, _client_backend


def llm_available() -> bool:
    client, backend = get_client()
    return client is not None and backend in ("openai", "wandb")


def active_backend() -> str:
    _, backend = get_client()
    return backend


def _parse_json(raw: str) -> dict[str, Any]:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    return json.loads(raw)


@op(name="llm.chat_json", kind="llm")
def chat_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 768,
    temperature: float = 0.4,
) -> dict[str, Any] | None:
    """Single-turn structured completion. Returns parsed JSON or None (heuristic)."""
    client, backend = get_client()
    if client is None:
        return None

    s = get_settings()
    mdl = model or s.negotiator_model
    try:
        resp = client.chat.completions.create(
            model=mdl,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return _parse_json(resp.choices[0].message.content)
    except Exception:
        # Any failure (rate limit, parse error, bad model) → safe heuristic fallback
        return None


@op(name="llm.chat_text", kind="llm")
def chat_text(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.5,
) -> str | None:
    """Plain-text completion (used for summaries / onboarding). None if heuristic."""
    client, backend = get_client()
    if client is None:
        return None
    s = get_settings()
    try:
        resp = client.chat.completions.create(
            model=model or s.negotiator_model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content
    except Exception:
        return None
