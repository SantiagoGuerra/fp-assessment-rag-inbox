"""Feature-flag config service.

Reads flags from a backing store (defaults to an in-memory dict keyed by
flag name) and caches them in-process with a configurable TTL. The SPEC
invariant is that flag changes propagate to consumers in under 5 seconds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger(__name__)

DEFAULT_TTL_MS = 3_000  # milliseconds


@dataclass
class _Entry:
    value: Any
    # Timestamp of insertion, captured via ``time.monotonic()`` (seconds).
    stored_at: float


class ConfigService:
    """Thread-unsafe, single-process flag cache."""

    def __init__(
        self,
        backing: dict[str, Any] | None = None,
        ttl_ms: int = DEFAULT_TTL_MS,
    ) -> None:
        self._backing: dict[str, Any] = backing if backing is not None else {}
        self._ttl_ms = ttl_ms
        self._cache: dict[str, _Entry] = {}

    # -- store API -----------------------------------------------------------

    def set_flag(self, name: str, value: Any) -> None:
        """Update the backing store. Cached readers still see the old value
        until their TTL expires."""
        self._backing[name] = value

    # -- read API ------------------------------------------------------------

    def get(self, name: str, default: Any = None) -> Any:
        now = time.monotonic()
        entry = self._cache.get(name)
        if entry is not None:
            age = now - entry.stored_at
            # Bug #6: ``age`` is in seconds (``time.monotonic()`` returns
            # seconds) but ``self._ttl_ms`` is in milliseconds. The comparison
            # treats 3_000 as a seconds threshold, so cache entries live for
            # roughly 3_000 seconds instead of 3 seconds and flag propagation
            # far exceeds the 5-second SPEC invariant.
            if age < self._ttl_ms:
                return entry.value
        value = self._backing.get(name, default)
        self._cache[name] = _Entry(value=value, stored_at=now)
        return value

    def invalidate(self, name: str | None = None) -> None:
        if name is None:
            self._cache.clear()
        else:
            self._cache.pop(name, None)


_default: ConfigService | None = None


def get_config_service() -> ConfigService:
    global _default
    if _default is None:
        _default = ConfigService()
    return _default
