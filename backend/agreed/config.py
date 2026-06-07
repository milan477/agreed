"""Central configuration. Reads from environment / .env, degrades gracefully.

Nothing here raises if a sponsor key is missing — the platform always has a
working offline path so the live demo never breaks.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from functools import lru_cache


def _load_dotenv() -> None:
    """Lightweight .env loader (no hard dependency on python-dotenv)."""
    try:
        from dotenv import load_dotenv  # type: ignore

        # search upward for a .env so it works from repo root or backend/
        here = pathlib.Path(__file__).resolve()
        for parent in [here.parent, *here.parents]:
            candidate = parent / ".env"
            if candidate.exists():
                load_dotenv(candidate, override=False)
                break
        return
    except Exception:
        pass

    # Manual fallback
    here = pathlib.Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / ".env"
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            break


_load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # LLM
    llm_backend: str  # "openai" | "wandb" | "heuristic"
    negotiator_model: str
    openai_api_key: str
    wandb_inference_base_url: str

    # Weave / W&B
    wandb_api_key: str
    wandb_entity: str
    weave_project: str

    # Sponsor keys
    e2b_api_key: str
    exa_api_key: str
    redis_url: str
    mem0_api_key: str
    database_url: str
    twilio_sid: str
    twilio_token: str
    twilio_from: str
    cors_origins: str

    # ── capability flags (computed) ──────────────────────────────────────────
    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_wandb(self) -> bool:
        return bool(self.wandb_api_key)

    @property
    def has_e2b(self) -> bool:
        return bool(self.e2b_api_key)

    @property
    def has_exa(self) -> bool:
        return bool(self.exa_api_key)

    @property
    def has_mem0(self) -> bool:
        return bool(self.mem0_api_key)

    @property
    def resolved_llm_backend(self) -> str:
        """Auto-detect the best available backend if not explicitly set."""
        if self.llm_backend in ("openai", "wandb", "heuristic"):
            return self.llm_backend
        if self.wandb_api_key:
            return "wandb"
        if self.openai_api_key:
            return "openai"
        return "heuristic"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        llm_backend=_get("AGREED_LLM_BACKEND"),
        negotiator_model=_get("NEGOTIATOR_MODEL", "gpt-4o-mini"),
        openai_api_key=_get("OPENAI_API_KEY"),
        wandb_inference_base_url=_get(
            "WANDB_INFERENCE_BASE_URL", "https://api.inference.wandb.ai/v1"
        ),
        wandb_api_key=_get("WANDB_API_KEY"),
        wandb_entity=_get("WANDB_ENTITY"),
        weave_project=_get("WEAVE_PROJECT") or _get("WANDB_PROJECT", "agreed"),
        e2b_api_key=_get("E2B_API_KEY"),
        exa_api_key=_get("EXA_API_KEY"),
        redis_url=_get("REDIS_URL"),
        mem0_api_key=_get("MEM0_API_KEY"),
        database_url=_get("DATABASE_URL"),
        twilio_sid=_get("TWILIO_ACCOUNT_SID"),
        twilio_token=_get("TWILIO_AUTH_TOKEN"),
        twilio_from=_get("TWILIO_FROM_NUMBER"),
        cors_origins=_get("CORS_ORIGINS"),
    )


def cors_origin_list() -> list[str]:
    raw = get_settings().cors_origins
    if not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


def capability_report() -> dict[str, object]:
    """Human-readable summary of what's live vs. running in fallback mode."""
    s = get_settings()
    return {
        "llm_backend": s.resolved_llm_backend,
        "negotiator_model": s.negotiator_model,
        "weave": "live" if s.has_wandb else "local-noop",
        "weave_project": f"{s.wandb_entity + '/' if s.wandb_entity else ''}{s.weave_project}",
        "e2b_sandbox": "live" if s.has_e2b else "local-process fallback",
        "exa_research": "live" if s.has_exa else "stub research",
        "mem0_memory": "live" if s.has_mem0 else "in-memory fallback",
        "redis": "configured" if s.redis_url else "in-memory fallback",
        "database": "postgres" if s.database_url else "sqlite fallback",
    }
