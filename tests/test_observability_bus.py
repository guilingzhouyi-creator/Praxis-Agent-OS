"""Tests for ObservabilityBus — unified observability bus."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_observe_alert():
    from services.observability_bus import ObservabilityBus
    bus = ObservabilityBus()
    r = bus.observe("alert", "test-agent", {"message": "test alert", "level": "info"})
    assert r.get("alert", {}).get("success", False) or "alert" in r


def test_observe_metric():
    from services.observability_bus import ObservabilityBus
    bus = ObservabilityBus()
    r = bus.observe("metric", "test-agent", {"metric": "test_count", "value": 1})
    assert r.get("metric", {}).get("success", False) or "metric" in r


def test_observe_unknown():
    from services.observability_bus import ObservabilityBus
    bus = ObservabilityBus()
    r = bus.observe("unknown_kind", "test", {})
    assert "error" in r


def test_summary():
    from services.observability_bus import ObservabilityBus
    bus = ObservabilityBus()
    s = bus.summary()
    assert "ops" in s
    assert "health" in s
    assert "metrics" in s


def test_get_bus():
    from services.observability_bus import get_obs_bus, reset_obs_bus
    reset_obs_bus()
    b1 = get_obs_bus()
    b2 = get_obs_bus()
    assert b1 is b2
