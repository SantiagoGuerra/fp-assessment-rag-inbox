"""Tests for :mod:`src.services.config_service`."""

from __future__ import annotations

from src.services.config_service import ConfigService


def test_config_returns_backing_value() -> None:
    svc = ConfigService(backing={"new_retriever": True})
    assert svc.get("new_retriever") is True
    assert svc.get("unknown", default="fallback") == "fallback"


def test_config_cache_respects_invalidate() -> None:
    svc = ConfigService(backing={"flag_a": "v1"}, ttl_ms=50)
    assert svc.get("flag_a") == "v1"
    # Update backing and force invalidation — reader must see the new value.
    svc.set_flag("flag_a", "v2")
    svc.invalidate("flag_a")
    assert svc.get("flag_a") == "v2"
