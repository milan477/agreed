"""Memory backends.

Redis covers three sponsor criteria in one: session/short-term store, response
cache, and semantic vector recall. Mem0 holds long-term structured user
preferences. Both degrade to in-process fallbacks so the demo runs offline.
All keys are namespaced by user_id for isolation.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from typing import Any

from ..config import get_settings
from ..observability import op, record_event


class ShortTermMemory:
    """Session memory + cache. Redis-backed when REDIS_URL is set."""

    def __init__(self) -> None:
        self._redis = None
        self._local: dict[str, tuple[float, Any]] = {}
        s = get_settings()
        if s.redis_url:
            try:
                import redis  # type: ignore

                self._redis = redis.from_url(s.redis_url, decode_responses=True)
                self._redis.ping()
            except Exception:
                self._redis = None

    def _key(self, user_id: str, key: str) -> str:
        return f"agreed:{user_id}:{key}"

    @op(name="memory.cache_set", kind="tool")
    def set(self, user_id: str, key: str, value: Any, ttl: int = 3600) -> None:
        payload = json.dumps(value)
        if self._redis is not None:
            self._redis.setex(self._key(user_id, key), ttl, payload)
        else:
            self._local[self._key(user_id, key)] = (time.time() + ttl, payload)

    @op(name="memory.cache_get", kind="tool")
    def get(self, user_id: str, key: str) -> Any | None:
        k = self._key(user_id, key)
        if self._redis is not None:
            raw = self._redis.get(k)
            return json.loads(raw) if raw else None
        entry = self._local.get(k)
        if not entry:
            return None
        expires, raw = entry
        if expires < time.time():
            self._local.pop(k, None)
            return None
        return json.loads(raw)

    @op(name="memory.cache_key", kind="tool")
    def cache_key(self, *parts: str) -> str:
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class LongTermMemory:
    """Structured user preference facts. Mem0-backed when MEM0_API_KEY is set."""

    def __init__(self) -> None:
        self._mem0 = None
        self._local: dict[str, list[dict]] = defaultdict(list)
        s = get_settings()
        if s.has_mem0:
            try:
                from mem0 import MemoryClient  # type: ignore

                self._mem0 = MemoryClient(api_key=s.mem0_api_key)
            except Exception:
                self._mem0 = None

    @op(name="memory.remember", kind="tool")
    def remember(self, user_id: str, fact: str, metadata: dict | None = None) -> None:
        if self._mem0 is not None:
            try:
                self._mem0.add([{"role": "user", "content": fact}], user_id=user_id, metadata=metadata or {})
                record_event("mem0_add", kind="tool", user=user_id)
                return
            except Exception:
                pass
        self._local[user_id].append({"fact": fact, "metadata": metadata or {}, "ts": time.time()})

    @op(name="memory.recall", kind="tool")
    def recall(self, user_id: str, query: str = "", limit: int = 5) -> list[dict]:
        if self._mem0 is not None:
            try:
                res = self._mem0.search(query or "preferences", user_id=user_id, limit=limit)
                return res if isinstance(res, list) else res.get("results", [])
            except Exception:
                pass
        return self._local.get(user_id, [])[-limit:]


_short: ShortTermMemory | None = None
_long: LongTermMemory | None = None


def short_term() -> ShortTermMemory:
    global _short
    if _short is None:
        _short = ShortTermMemory()
    return _short


def long_term() -> LongTermMemory:
    global _long
    if _long is None:
        _long = LongTermMemory()
    return _long
