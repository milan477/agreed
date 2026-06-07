"""W&B Weave observability.

Goal from the build order: "Weave wired in everywhere — do this first, never
break it." This module makes the `@op` decorator safe to apply to every agent,
tool, LLM, and A2A call. If Weave is not installed or no W&B key is present, the
decorator becomes a transparent pass-through and a lightweight local tracer keeps
the in-app trace view working so the demo always has something to show.
"""

from __future__ import annotations

import functools
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import get_settings

# ── local fallback tracer ─────────────────────────────────────────────────────
# Always-on, in-process span recorder. Powers the in-UI trace summary even when
# the hosted Weave dashboard isn't configured.


@dataclass
class Span:
    id: str
    name: str
    parent_id: str | None
    started_at: float
    ended_at: float | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        if self.ended_at is None:
            return 0.0
        return round((self.ended_at - self.started_at) * 1000, 1)


class LocalTracer:
    """Thread-safe in-memory span collector grouped by trace_id."""

    def __init__(self) -> None:
        self._traces: dict[str, list[Span]] = {}
        self._lock = threading.Lock()

    def add(self, trace_id: str, span: Span) -> None:
        with self._lock:
            self._traces.setdefault(trace_id, []).append(span)

    def get(self, trace_id: str) -> list[Span]:
        with self._lock:
            return list(self._traces.get(trace_id, []))

    def all_trace_ids(self) -> list[str]:
        with self._lock:
            return list(self._traces.keys())


_tracer = LocalTracer()
_current_trace: ContextVar[str | None] = ContextVar("agreed_trace_id", default=None)
_current_span: ContextVar[str | None] = ContextVar("agreed_span_id", default=None)

# ── Weave init (best effort, never raises) ────────────────────────────────────
_weave = None
_weave_inited = False


def init_observability() -> dict[str, Any]:
    """Initialize Weave if possible. Idempotent and exception-safe."""
    global _weave, _weave_inited
    if _weave_inited:
        return {"weave": _weave is not None}
    _weave_inited = True

    s = get_settings()
    if not s.has_wandb:
        return {"weave": False, "reason": "no WANDB_API_KEY (local tracer active)"}
    try:
        import weave  # type: ignore

        project = f"{s.wandb_entity}/{s.weave_project}" if s.wandb_entity else s.weave_project
        weave.init(project)
        _weave = weave
        return {"weave": True, "project": project}
    except Exception as exc:  # pragma: no cover - depends on optional dep
        return {"weave": False, "reason": f"weave init failed: {exc} (local tracer active)"}


def _short(value: Any, limit: int = 600) -> Any:
    """Truncate large values so traces stay readable."""
    try:
        if isinstance(value, str) and len(value) > limit:
            return value[:limit] + f"... (+{len(value) - limit} chars)"
        return value
    except Exception:
        return str(value)[:limit]


def op(name: str | None = None, kind: str = "function") -> Callable:
    """Decorator: trace a callable in Weave (if live) and the local tracer.

    `kind` is a semantic tag, e.g. "agent", "llm", "tool", "a2a", "graph".
    """

    def decorator(func: Callable) -> Callable:
        span_name = name or f"{func.__module__.split('.')[-1]}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            trace_id = _current_trace.get() or "untracked"
            parent_id = _current_span.get()
            span = Span(
                id=uuid.uuid4().hex[:12],
                name=span_name,
                parent_id=parent_id,
                started_at=time.time(),
                inputs={"args": _short(repr(args)), "kwargs": _short(repr(kwargs))},
                attributes={"kind": kind},
            )
            token = _current_span.set(span.id)
            try:
                result = func(*args, **kwargs)
                span.output = _short(repr(result))
                return result
            except Exception as exc:
                span.error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                span.ended_at = time.time()
                _tracer.add(trace_id, span)
                _current_span.reset(token)

        # Layer Weave's own op on top when available so it shows in the hosted UI.
        if _weave is not None:
            try:
                return _weave.op(name=span_name)(wrapper)  # type: ignore[attr-defined]
            except Exception:
                return wrapper
        return wrapper

    return decorator


class trace_context:
    """Context manager that scopes a logical trace (one negotiation = one trace)."""

    def __init__(self, trace_id: str | None = None) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex
        self._token = None

    def __enter__(self) -> str:
        self._token = _current_trace.set(self.trace_id)
        return self.trace_id

    def __exit__(self, *exc: Any) -> None:
        if self._token is not None:
            _current_trace.reset(self._token)


def record_event(name: str, kind: str = "event", **attributes: Any) -> None:
    """Record a point-in-time event into the current trace (no wrapped call)."""
    trace_id = _current_trace.get() or "untracked"
    now = time.time()
    span = Span(
        id=uuid.uuid4().hex[:12],
        name=name,
        parent_id=_current_span.get(),
        started_at=now,
        ended_at=now,
        attributes={"kind": kind, **{k: _short(v) for k, v in attributes.items()}},
    )
    _tracer.add(trace_id, span)


def get_spans(trace_id: str) -> list[dict[str, Any]]:
    """Return spans for a trace as plain dicts (for the API / UI)."""
    spans = _tracer.get(trace_id)
    return [
        {
            "id": s.id,
            "name": s.name,
            "parent_id": s.parent_id,
            "kind": s.attributes.get("kind", "function"),
            "duration_ms": s.duration_ms,
            "inputs": s.inputs,
            "output": s.output,
            "error": s.error,
            "attributes": s.attributes,
        }
        for s in spans
    ]


def weave_trace_url() -> str | None:
    """Best-effort URL to the hosted Weave dashboard for this project."""
    s = get_settings()
    if not s.has_wandb:
        return None
    entity = s.wandb_entity or "<your-entity>"
    return f"https://wandb.ai/{entity}/{s.weave_project}/weave"
