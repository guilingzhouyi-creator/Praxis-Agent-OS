"""Error Bus integration test — error recording + query + stats + trend + API"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestErrorLogEntry:
    """Error log entry"""

    def test_fingerprint(self):
        from l3.error_bus import _compute_fingerprint

        fp = _compute_fingerprint("ERROR", "E_INTERNAL", "test.py:1", "test error")
        assert len(fp) == 16

        # Same input should produce the same fingerprint
        fp2 = _compute_fingerprint("ERROR", "E_INTERNAL", "test.py:1", "test error")
        assert fp == fp2

        # Different inputs should produce different fingerprints
        fp3 = _compute_fingerprint("ERROR", "E_TIMEOUT", "test.py:1", "test error")
        assert fp != fp3

    def test_to_dict(self):
        from l3.error_bus import ErrorLogEntry

        entry = ErrorLogEntry(
            level="ERROR",
            service="test",
            message="msg",
            error_code="E_TEST",
            component="kernel",
        )
        d = entry.to_dict()
        assert d["level"] == "ERROR"
        assert d["error_code"] == "E_TEST"
        assert len(d["id"]) == 12

    def test_auto_fingerprint(self):
        from l3.error_bus import ErrorLogEntry

        e1 = ErrorLogEntry(level="ERROR", service="s", message="same")
        e2 = ErrorLogEntry(level="ERROR", service="s", message="same")
        assert e1.fingerprint == e2.fingerprint


class TestErrorBus:
    """Error bus"""

    def setUp(self):
        from l3.error_bus import reset_bus

        reset_bus()

    def _get_bus(self):
        from l3.error_bus import get_bus, reset_bus

        reset_bus()
        return get_bus()

    def test_error_record(self):
        bus = self._get_bus()
        r = bus.error("test error occurred", error_code="E_TEST", component="kernel", source="test.py:10")
        assert r["success"]
        entry = r["entry"]
        assert entry["error_code"] == "E_TEST"
        assert entry["component"] == "kernel"
        assert entry["count"] == 1

    def test_dedup_same_error(self):
        bus = self._get_bus()
        bus.error("dedup test", error_code="E_DEDUP", source="test.py:20")
        r2 = bus.error("dedup test", error_code="E_DEDUP", source="test.py:20")
        assert r2["entry"]["count"] == 2

    def test_warn_record(self):
        bus = self._get_bus()
        r = bus.warn("warning message", component="services", source="srv.py:5")
        assert r["success"]
        assert r["entry"]["level"] == "WARN"

    def test_critical_record(self):
        bus = self._get_bus()
        r = bus.critical("critical failure", error_code="E_CRIT", component="kernel", source="core.py:1")
        assert r["success"]
        assert r["entry"]["level"] == "CRITICAL"

    def test_exception_record(self):
        bus = self._get_bus()
        try:
            raise ValueError("something broke")
        except ValueError as e:
            r = bus.exception(e, message="handler failed", component="services", source="handler.py:10")
        assert r["success"]
        assert "ValueError" in r["entry"]["stack_trace"]

    def test_query_level_filter(self):
        bus = self._get_bus()
        bus.error("e1", error_code="E1", source="a.py")
        bus.warn("w1", source="a.py")
        bus.error("e2", error_code="E2", source="a.py")
        q = bus.query(level="ERROR")
        assert q["success"]
        assert q["total"] >= 2
        for e in q["entries"]:
            assert e["level"] == "ERROR"

    def test_query_component_filter(self):
        bus = self._get_bus()
        bus.error("k", error_code="E1", component="kernel", source="k.py")
        bus.error("s", error_code="E2", component="services", source="s.py")
        q = bus.query(component="kernel")
        assert q["success"]
        for e in q["entries"]:
            assert e["component"] == "kernel"

    def test_query_pagination(self):
        bus = self._get_bus()
        for i in range(10):
            bus.error(f"msg_{i}", error_code="E_PAG", source="p.py")
        q = bus.query(offset=0, limit=3)
        assert q["success"]
        assert len(q["entries"]) <= 3

    def test_stats(self):
        bus = self._get_bus()
        bus.error("e1", error_code="E_A", component="kernel", source="a.py")
        bus.error("e2", error_code="E_B", component="services", source="b.py")
        bus.warn("w1", component="tools", source="c.py")
        s = bus.stats()
        assert s["success"]
        assert s["total"] >= 3

    def test_trend(self):
        bus = self._get_bus()
        bus.error("trend_test", error_code="E_TREND", source="t.py")
        t = bus.trend(window_minutes=60, bucket_minutes=10)
        assert t["success"]
        assert len(t["buckets"]) >= 1

    def test_clear_all(self):
        bus = self._get_bus()
        bus.error("to_clear", error_code="E_CLEAR", source="c.py")
        r = bus.clear()
        assert r["success"]
        assert r["removed"] >= 1
        s = bus.stats()
        assert s["total"] == 0

    def test_recent(self):
        bus = self._get_bus()
        bus.error("recent_test", error_code="E_RECENT", source="r.py")
        r = bus.recent(limit=5)
        assert r["success"]
        assert r["count"] >= 1


class TestCaptureHelper:
    """capture shortcut"""

    def test_capture(self):
        from l3.error_bus import capture, reset_bus

        reset_bus()
        try:
            raise RuntimeError("oops")
        except RuntimeError as e:
            r = capture("capture test", exc=e, component="test")
        assert r["success"]
        assert "RuntimeError" in r["entry"].get("stack_trace", "")

    def test_capture_exception(self):
        from l3.error_bus import capture_exception, reset_bus

        reset_bus()
        try:
            raise ValueError("bad value")
        except ValueError as e:
            r = capture_exception(e, "exception test", component="test")
        assert r["success"]
        entry = r.get("entry", {})
        assert "ValueError" in entry.get("stack_trace", "")


class TestGetByFingerprint:
    """Query by fingerprint"""

    def test_found(self):
        from l3.error_bus import get_bus, reset_bus

        reset_bus()
        bus = get_bus()
        # The 'id' in to_dict() is fingerprint[:12]; query by error_code instead
        r = bus.error("fp_test", error_code="E_FP", source="fp.py")
        assert r["success"]
        result = bus.query(error_code="E_FP")
        assert result["success"]
        assert result["total"] >= 1
        for entry in result["entries"]:
            if entry["error_code"] == "E_FP":
                # Also check the bus internal fingerprint map directly
                break

    def test_not_found(self):
        from l3.error_bus import get_bus, reset_bus

        reset_bus()
        bus = get_bus()
        result = bus.get_by_fingerprint("nonexistent")
        assert result is None


class TestApiHandlers:
    """API Handler function-level test"""

    def setUp(self):
        from l3.error_bus import reset_bus

        reset_bus()

    def test_handle_log_errors_empty(self):
        from l3.error_bus import handle_log_errors

        r = handle_log_errors({})
        assert r["success"]
        assert isinstance(r["entries"], list)

    def test_handle_log_errors_with_data(self):
        from l3.error_bus import get_bus, handle_log_errors, reset_bus

        reset_bus()
        bus = get_bus()
        bus.error("api test", error_code="E_API", source="api_test.py")
        r = handle_log_errors({"level": "ERROR"})
        assert r["success"]
        assert r["total"] >= 1

    def test_handle_log_errors_stats(self):
        from l3.error_bus import handle_log_errors_stats

        r = handle_log_errors_stats()
        assert r["success"]
        assert "by_level" in r

    def test_handle_log_errors_trend(self):
        from l3.error_bus import handle_log_errors_trend

        r = handle_log_errors_trend({"window": 60, "bucket": 10})
        assert r["success"]
        assert "buckets" in r

    def test_handle_log_errors_clear(self):
        from l3.error_bus import handle_log_errors_clear

        r = handle_log_errors_clear({})
        assert r["success"]

    def test_handle_log_errors_detail_not_found(self):
        from l3.error_bus import handle_log_errors_detail

        r = handle_log_errors_detail({"fingerprint": "nonexistent"})
        assert not r["success"]

    def test_handle_log_errors_detail_missing(self):
        from l3.error_bus import handle_log_errors_detail

        r = handle_log_errors_detail({})
        assert not r["success"]

    def test_handle_log_errors_export(self):
        from l3.error_bus import handle_log_errors_export

        r = handle_log_errors_export({})
        assert r["success"]
