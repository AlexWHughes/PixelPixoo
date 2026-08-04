"""Simple monotonic TTL cache shared by screen fetch helpers."""

from __future__ import annotations

import time
from typing import Generic, TypeVar

T = TypeVar("T")


class TtlCache(Generic[T]):
    """In-memory cache keyed by string with monotonic TTL."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, T]] = {}

    def get(self, key: str, ttl: float) -> T | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        cached_at, value = entry
        if time.monotonic() - cached_at < ttl:
            return value
        return None

    def get_stale(self, key: str) -> T | None:
        entry = self._store.get(key)
        return entry[1] if entry else None

    def get_entry(self, key: str) -> tuple[float, T] | None:
        return self._store.get(key)

    def set(self, key: str, value: T) -> None:
        self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        self._store.clear()
