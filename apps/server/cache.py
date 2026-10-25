"""
Task 19: Caches query embeddings, lecture searches and chat answers, so a repeated question
skips Gemini and Supabase and comes back in milliseconds.

With REDIS_URL set (a local `redis-server`, or a free hosted Redis such as Upstash) the cache is
shared by every uvicorn worker and survives restarts. Without it, an in-process LRU cache is
used, which needs nothing installed. Both cost $0.

The cache can never fail a request: if Redis is unreachable, reads miss, writes are skipped,
and the memory cache takes over for REDIS_RETRY_SECONDS before Redis is tried again.
"""

import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

# Read apps/server/.env before the settings below (it never overrides the shell's variables)
load_dotenv(Path(__file__).resolve().parent / ".env")

TAG = "CACHE"

# Gemini returns the same vector for the same text and model, so embeddings keep for a month
EMBEDDING_TTL_SECONDS = int(os.getenv("CACHE_EMBEDDING_TTL_SECONDS", str(30 * 86400)))
# A lecture's chunks only change when it is re-indexed, which also bumps its version below
SEARCH_TTL_SECONDS = int(os.getenv("CACHE_SEARCH_TTL_SECONDS", str(6 * 3600)))
# Answers are cached for a day; set to 0 to always ask Gemini again
ANSWER_TTL_SECONDS = int(os.getenv("CACHE_ANSWER_TTL_SECONDS", str(86400)))
MEMORY_MAX_ITEMS = int(os.getenv("CACHE_MEMORY_MAX_ITEMS", "5000"))
KEY_PREFIX = "vidyapulse:"
# Redis must answer fast or not at all: a slow cache would cost more than it saves
REDIS_TIMEOUT_SECONDS = float(os.getenv("REDIS_TIMEOUT_SECONDS", "0.3"))
REDIS_RETRY_SECONDS = 30


def log(message: str) -> None:
    print(f"[{TAG}] {message}", flush=True)


def normalize_text(text: str) -> str:
    """Case and spacing don't change the meaning of a question, so they share a cache entry."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:32]


class MemoryCache:
    """A thread-safe LRU cache with per-entry expiry, for a single uvicorn process."""

    name = "memory"

    def __init__(self, max_items: int = MEMORY_MAX_ITEMS):
        self.max_items = max_items
        self._items: "OrderedDict[str, tuple]" = OrderedDict()
        self._counters: Dict[str, int] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at is not None and expires_at <= time.monotonic():
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def set(self, key: str, value: str, ttl: Optional[int]) -> None:
        expires_at = time.monotonic() + ttl if ttl else None
        with self._lock:
            self._items[key] = (value, expires_at)
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def get_counter(self, key: str) -> int:
        with self._lock:
            return self._counters.get(key, 0)

    def incr(self, key: str) -> int:
        # Counters are kept apart from the LRU items so eviction can never reset a version
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1
            return self._counters[key]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._counters.clear()


class RedisCache:
    """Redis with short timeouts. While Redis is down, a MemoryCache stands in for it."""

    name = "redis"

    def __init__(self, url: str, client=None):
        if client is None:
            import redis

            client = redis.Redis.from_url(
                url,
                socket_timeout=REDIS_TIMEOUT_SECONDS,
                socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
            )
        self.client = client
        self.fallback = MemoryCache()
        self._down_until = 0.0

    def _available(self) -> bool:
        return time.monotonic() >= self._down_until

    def _failed(self, error: Exception) -> None:
        if self._available():
            log(
                f"Redis is unreachable ({error}). Using the in-memory cache for "
                f"{REDIS_RETRY_SECONDS}s, then trying Redis again."
            )
        self._down_until = time.monotonic() + REDIS_RETRY_SECONDS

    def _run(self, redis_call, fallback_call):
        if self._available():
            try:
                return redis_call()
            except Exception as e:
                self._failed(e)
        return fallback_call()

    def get(self, key: str) -> Optional[str]:
        def from_redis():
            value = self.client.get(KEY_PREFIX + key)
            return value.decode("utf-8") if isinstance(value, bytes) else value

        return self._run(from_redis, lambda: self.fallback.get(key))

    def set(self, key: str, value: str, ttl: Optional[int]) -> None:
        self._run(
            lambda: self.client.set(KEY_PREFIX + key, value, ex=ttl or None),
            lambda: self.fallback.set(key, value, ttl),
        )

    def get_counter(self, key: str) -> int:
        return self._run(
            lambda: int(self.client.get(KEY_PREFIX + key) or 0),
            lambda: self.fallback.get_counter(key),
        )

    def incr(self, key: str) -> int:
        return self._run(
            lambda: int(self.client.incr(KEY_PREFIX + key)),
            lambda: self.fallback.incr(key),
        )

    def clear(self) -> None:
        def clear_redis():
            for key in self.client.scan_iter(match=KEY_PREFIX + "*"):
                self.client.delete(key)

        self._run(clear_redis, lambda: None)
        self.fallback.clear()


_backend = None
_backend_lock = threading.Lock()
_enabled = True
_stats = {"hits": 0, "misses": 0}


def get_backend():
    """Picks Redis when REDIS_URL is set, else memory. Made on first use, never at import time."""
    global _backend
    with _backend_lock:
        if _backend is None:
            url = os.getenv("REDIS_URL", "").strip()
            if url:
                try:
                    _backend = RedisCache(url)
                    log(f"Using Redis at {url.split('@')[-1]}.")
                except Exception as e:
                    log(f"Could not set up Redis ({e}); using the in-memory cache.")
                    _backend = MemoryCache()
            else:
                _backend = MemoryCache()
                log(
                    "Using the in-memory cache (set REDIS_URL to share it across workers)."
                )
        return _backend


def configure(backend=None) -> None:
    """Swaps the backend (tests, benchmarks). None means: pick again from REDIS_URL on next use."""
    global _backend
    with _backend_lock:
        _backend = backend
    reset_stats()


@contextmanager
def disabled():
    """Within this block every read misses and nothing is written (cold-path benchmarks)."""
    global _enabled
    previous, _enabled = _enabled, False
    try:
        yield
    finally:
        _enabled = previous


def get_json(key: str) -> Optional[Any]:
    if not _enabled:
        return None
    raw = get_backend().get(key)
    if raw is None:
        _stats["misses"] += 1
        return None
    _stats["hits"] += 1
    try:
        return json.loads(raw)
    except ValueError:
        return None


def set_json(key: str, value: Any, ttl: int) -> None:
    if not _enabled or ttl <= 0:
        return
    get_backend().set(key, json.dumps(value, ensure_ascii=False), ttl)


def lecture_version(lecture_id: str) -> int:
    """Part of every per-lecture key, so bumping it retires all of the lecture's entries at once."""
    return get_backend().get_counter(f"lecture-version:{lecture_id}")


def invalidate_lecture(lecture_id: str) -> None:
    """Call after a lecture's chunks change (re-indexing), so no search or answer is stale."""
    get_backend().incr(f"lecture-version:{lecture_id}")


def lecture_key(kind: str, lecture_id: str, *parts: str) -> str:
    return ":".join(
        [kind, str(lecture_id), f"v{lecture_version(lecture_id)}", *map(str, parts)]
    )


def stats() -> Dict[str, Any]:
    total = _stats["hits"] + _stats["misses"]
    return {
        "backend": get_backend().name,
        "enabled": _enabled,
        "hits": _stats["hits"],
        "misses": _stats["misses"],
        "hit_rate": round(_stats["hits"] / total, 3) if total else None,
    }


def reset_stats() -> None:
    _stats["hits"] = _stats["misses"] = 0
