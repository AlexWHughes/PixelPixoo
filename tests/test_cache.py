"""Tests for pixelpixoo.cache.TtlCache."""

from __future__ import annotations

from types import SimpleNamespace

import pixelpixoo.cache as cache_mod
from pixelpixoo.cache import TtlCache


def _clock_at(now: float, monkeypatch) -> None:
    monkeypatch.setattr(cache_mod, "time", SimpleNamespace(monotonic=lambda: now))


def test_get_returns_value_within_ttl(monkeypatch) -> None:
    cache: TtlCache[str] = TtlCache()
    _clock_at(100.0, monkeypatch)
    cache.set("k", "v")
    _clock_at(109.9, monkeypatch)
    assert cache.get("k", ttl=10.0) == "v"


def test_get_expires_after_ttl(monkeypatch) -> None:
    cache: TtlCache[str] = TtlCache()
    _clock_at(100.0, monkeypatch)
    cache.set("k", "v")
    _clock_at(110.0, monkeypatch)
    assert cache.get("k", ttl=10.0) is None


def test_missing_key_returns_none() -> None:
    cache: TtlCache[str] = TtlCache()
    assert cache.get("nope", ttl=10.0) is None
    assert cache.get_stale("nope") is None
    assert cache.get_entry("nope") is None


def test_stale_serves_expired_value(monkeypatch) -> None:
    cache: TtlCache[str] = TtlCache()
    _clock_at(100.0, monkeypatch)
    cache.set("k", "stale")
    _clock_at(999.0, monkeypatch)
    assert cache.get("k", ttl=1.0) is None
    assert cache.get_stale("k") == "stale"
    entry = cache.get_entry("k")
    assert entry is not None and entry[1] == "stale"


def test_set_overwrites_and_clear(monkeypatch) -> None:
    cache: TtlCache[int] = TtlCache()
    _clock_at(1.0, monkeypatch)
    cache.set("k", 1)
    _clock_at(2.0, monkeypatch)
    cache.set("k", 2)
    assert cache.get("k", ttl=10.0) == 2
    cache.clear()
    assert cache.get("k", ttl=10.0) is None
