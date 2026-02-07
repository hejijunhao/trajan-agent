"""
Request-scoped caching using contextvars.

Provides a per-request cache that is automatically cleared between requests.
This prevents duplicate database queries within a single request lifecycle.

Use cases:
- get_effective_access() called multiple times for the same product/user
- get_member_role() called multiple times for the same org/user
- User preferences fetched multiple times during request processing

The cache is task-local (like thread-local for async), so parallel
requests don't pollute each other's caches.
"""

import logging
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

# ContextVar stores a dict per async task (request)
# Note: default=None is safer than default={} (mutable defaults)
_request_cache: ContextVar[dict[str, Any] | None] = ContextVar("request_cache", default=None)


def get_request_cache() -> dict[str, Any]:
    """
    Get the current request's cache dictionary.

    Returns the cache dict for the current async task. Creates a new
    empty dict if none exists (e.g., outside request context).
    """
    cache = _request_cache.get()
    if cache is None:
        cache = {}
        _request_cache.set(cache)
    return cache


def set_request_cache_value(key: str, value: Any) -> None:
    """Store a value in the request cache."""
    cache = get_request_cache()
    cache[key] = value


def get_request_cache_value(key: str) -> Any | None:
    """Get a value from the request cache, or None if not present."""
    cache = get_request_cache()
    return cache.get(key)


def clear_request_cache() -> None:
    """
    Clear the request cache.

    Called automatically by middleware at the start of each request
    to ensure a clean slate.
    """
    _request_cache.set({})


def request_cache_key(*parts: Any) -> str:
    """
    Generate a cache key from multiple parts.

    Usage:
        key = request_cache_key("access", product_id, user_id)
    """
    return ":".join(str(p) for p in parts)
