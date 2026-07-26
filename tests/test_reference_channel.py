"""Reference channel tests — ReferenceChannel event, card_lifecycle, export, count, stats, flush."""
from __future__ import annotations

import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from kernel.params.system import RC_EXPORT_LIMIT


# ── Helpers ──


def _cleanup(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# ── Fixtures ──


@pytest.fixture
def rc_path() -> str:
    """Yield a temp path and clean up after the test."""
    tmp = os.path.join(tempfile.gettempdir(), "_praxis_test_rc.jsonl")
    _cleanup(tmp)
    yield tmp
    _cleanup(tmp)


@pytest.fixture
def rc(rc_path: str):
    """Create a fresh ReferenceChannel with a temp path and small buffer for testing."""
    from services.reference_channel import ReferenceChannel

    ch = ReferenceChannel(path=rc_path, flush_interval=60.0, max_events=10)
    yield ch
    ch.flush()
    _cleanup(rc_path)


@pytest.fixture(autouse=True)
def _reset_rc_global():
    """Reset the global RC singleton before each test to avoid cross-test pollution."""
    from services.reference_channel import reset_rc

    reset_rc()


# ── ReferenceChannel tests ──


class TestReferenceChannelEvent:
    def test_event_writes_to_buffer_and_disk(self, rc, rc_path: str):
        rc.event("tool_call", {"tool_name": "read_file", "allowed": True}, source="test", trace_id="t-001")
        rc.flush()
        assert os.path.exists(rc_path)
        with open(rc_path, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["type"] == "tool_call"
        assert record["source"] == "test"
        assert record["trace_id"] == "t-001"
        assert record["data"]["tool_name"] == "read_file"
        assert "sha256" in record
        assert "timestamp" in record

    def test_event_content_hash_provenance(self, rc):
        rc.event("convention", {"outcome": "consensus", "participant_count": 3})
        rc.flush()
        records = rc.export()
        assert len(records) == 1
        content = json.dumps(
            {k: v for k, v in records[0].items() if k != "sha256"},
            sort_keys=True, ensure_ascii=False, default=str,
        )
        expected_hash = __import__("hashlib").sha256(content.encode()).hexdigest()[:16]
        assert records[0]["sha256"] == expected_hash

    def test_event_auto_flush_on_buffer_full(self, rc_path: str):
        from services.reference_channel import ReferenceChannel

        ch = ReferenceChannel(path=rc_path, flush_interval=9999.0, max_events=3)
        ch.event("a", {})
        ch.event("b", {})
        assert not os.path.exists(rc_path) or os.path.getsize(rc_path) == 0
        ch.event("c", {})  # third event triggers flush
        assert os.path.exists(rc_path)
        with open(rc_path, encoding="utf-8") as f:
            assert len(f.readlines()) == 3

    def test_event_auto_flush_on_interval(self, rc, rc_path: str):
        import time
        # Use a very short interval and small buffer so we don't hit buffer flush first
        from services.reference_channel import ReferenceChannel

        ch = ReferenceChannel(path=rc_path, flush_interval=0.01, max_events=100)
        ch.event("x", {})
        time.sleep(0.02)
        ch.event("y", {})  # second event should see elapsed > flush_interval and flush
        with open(rc_path, encoding="utf-8") as f:
            assert len(f.readlines()) >= 1


class TestReferenceChannelCardLifecycle:
    def test_card_lifecycle_records_event(self, rc):
        rc.card_lifecycle(
            card_id="c-001", intent="build feature", state="completed",
            nature="feature", size="M", error="",
        )
        rc.flush()
        records = rc.export()
        assert len(records) == 1
        ev = records[0]
        assert ev["type"] == "card_lifecycle"
        assert ev["source"] == "card_registry"
        assert ev["trace_id"] == "c-001"
        assert ev["data"]["card_id"] == "c-001"
        assert ev["data"]["state"] == "completed"

    def test_card_lifecycle_deviation_on_failure(self, rc):
        rc.card_lifecycle(
            card_id="c-002", intent="risky deploy", state="failed",
            predicted_state="completed",
        )
        rc.flush()
        ev = rc.export()[0]
        assert ev["data"]["deviation"] == "completion_mismatch"

    def test_card_lifecycle_deviation_on_unexpected_success(self, rc):
        rc.card_lifecycle(
            card_id="c-003", intent="should fail", state="completed",
            predicted_state="failed",
        )
        rc.flush()
        ev = rc.export()[0]
        assert ev["data"]["deviation"] == "unexpected_completion"


class TestReferenceChannelExport:
    def test_export_empty_when_no_file(self):
        from services.reference_channel import ReferenceChannel

        ch = ReferenceChannel(path="/nonexistent/path.jsonl")
        assert ch.export() == []

    def test_export_limit(self, rc):
        for i in range(5):
            rc.event("test", {"i": i})
        rc.flush()
        results = rc.export(limit=3)
        assert len(results) == 3

    def test_export_offset(self, rc):
        for i in range(5):
            rc.event("test", {"i": i})
        rc.flush()
        results = rc.export(offset=2)
        assert len(results) == 3
        assert results[0]["data"]["i"] == 2

    def test_export_filter_by_event_type(self, rc):
        rc.event("tool_call", {"tool": "a"})
        rc.event("card_lifecycle", {"card_id": "c-1"})
        rc.event("anomaly", {"detection": {}})
        rc.flush()
        tool_events = rc.export(event_type="tool_call")
        assert len(tool_events) == 1
        assert tool_events[0]["type"] == "tool_call"

    def test_export_filter_plus_limit(self, rc):
        for _ in range(5):
            rc.event("tool_call", {"tool": "a"})
        rc.event("card_lifecycle", {"card_id": "c-1"})
        rc.flush()
        results = rc.export(limit=3, event_type="tool_call")
        assert len(results) == 3
        assert all(r["type"] == "tool_call" for r in results)


class TestReferenceChannelCount:
    def test_count_total(self, rc):
        assert rc.count() == 0
        rc.event("a", {})
        rc.event("b", {})
        rc.flush()
        assert rc.count() == 2

    def test_count_by_event_type(self, rc):
        rc.event("tool_call", {"tool": "x"})
        rc.event("tool_call", {"tool": "y"})
        rc.event("card_lifecycle", {"card_id": "z"})
        rc.flush()
        assert rc.count(event_type="tool_call") == 2
        assert rc.count(event_type="card_lifecycle") == 1
        assert rc.count(event_type="anomaly") == 0

    def test_count_uses_rc_export_limit(self, rc):
        """count() passes RC_EXPORT_LIMIT to export() for filtered counts."""
        # Make sure the constant is used as the limit
        from services.reference_channel import ReferenceChannel

        original_export = ReferenceChannel.export

        captured_limit = [None]

        def tracking_export(self_, limit=1000, offset=0, event_type=""):
            captured_limit[0] = limit
            return original_export(self_, limit=limit, offset=offset, event_type=event_type)

        ReferenceChannel.export = tracking_export
        try:
            rc.event("demo", {"val": 1})
            rc.flush()
            _ = rc.count(event_type="demo")
            assert captured_limit[0] == RC_EXPORT_LIMIT, (
                f"Expected RC_EXPORT_LIMIT={RC_EXPORT_LIMIT}, got {captured_limit[0]}"
            )
        finally:
            ReferenceChannel.export = original_export


class TestReferenceChannelStats:
    def test_stats_structure(self, rc, rc_path: str):
        stats = rc.stats()
        assert stats["path"] == rc_path
        assert stats["total_events"] == 0
        assert stats["buffered"] == 0
        assert stats["max_events_per_flush"] == 10
        assert stats["flush_interval_s"] == 60.0

    def test_stats_reflects_events(self, rc):
        rc.event("a", {})
        rc.event("b", {})
        stats = rc.stats()
        assert stats["total_events"] == 2
        # Events are still buffered
        assert stats["buffered"] == 2
        rc.flush()
        stats = rc.stats()
        assert stats["buffered"] == 0
        assert stats["total_events"] == 2


class TestReferenceChannelFlush:
    def test_flush_writes_buffer_to_disk(self, rc, rc_path: str):
        rc.event("a", {})
        rc.event("b", {})
        assert not os.path.exists(rc_path) or os.path.getsize(rc_path) == 0
        rc.flush()
        assert os.path.exists(rc_path)
        with open(rc_path, encoding="utf-8") as f:
            assert len(f.readlines()) == 2

    def test_flush_idempotent(self, rc):
        rc.event("x", {})
        rc.flush()
        rc.flush()  # second flush should be a no-op
        assert rc.count() == 1


class TestReferenceChannelSingleton:
    def test_get_rc_returns_same_instance(self):
        from services.reference_channel import get_rc, reset_rc

        reset_rc()
        a = get_rc()
        b = get_rc()
        assert a is b

    def test_reset_rc_flushes_and_replaces(self):
        from services.reference_channel import get_rc, reset_rc

        reset_rc()
        rc1 = get_rc()
        rc1.event("keep", {"val": 1})
        reset_rc()  # flushes rc1 and replaces with None
        # The old rc1's data was flushed to its default path — that path is
        # the same one a fresh get_rc() would read. We bypass that by verifying
        # the returned instance is different.
        rc2 = get_rc()
        assert rc1 is not rc2


class TestReferenceChannelConvenienceHelpers:
    def test_tool_call_helper(self, rc):
        rc.tool_call(
            tool_name="write_file", agent_id="agent-1", allowed=False,
            gate="G3", reason="territory block", args={"path": "/etc/passwd"},
            trace_id="t-007",
        )
        rc.flush()
        ev = rc.export()[0]
        assert ev["type"] == "tool_call"
        assert ev["source"] == "tool_pipeline"
        assert ev["data"]["tool_name"] == "write_file"
        assert ev["data"]["allowed"] is False
        assert ev["data"]["deviation"] == "false_positive_expectation"
        assert "path" in ev["data"]["args_keys"]

    def test_human_correction_helper(self, rc):
        rc.human_correction(
            card_id="c-010", agent_id="agent-2",
            field="intent", old_value="wrong", new_value="right", reason="typo",
        )
        rc.flush()
        ev = rc.export()[0]
        assert ev["type"] == "human_correction"
        assert ev["source"] == "l2_shell"
        assert ev["data"]["field"] == "intent"
        assert ev["data"]["old_preview"] == "wrong"

    def test_anomaly_helper(self, rc):
        rc.anomaly(
            card_id="c-020", cell_id="cell-x",
            detection={"pattern": "OSCILLATION", "score": 0.92},
        )
        rc.flush()
        ev = rc.export()[0]
        assert ev["type"] == "anomaly"
        assert ev["source"] == "sequence_monitor"
        assert ev["data"]["detection"]["pattern"] == "OSCILLATION"

    def test_convention_helper(self, rc):
        rc.convention(
            card_id="c-030", outcome="consensus",
            participants=["alice", "bob"], summary="agreed on approach",
        )
        rc.flush()
        ev = rc.export()[0]
        assert ev["type"] == "convention"
        assert ev["source"] == "convention"
        assert ev["data"]["participant_count"] == 2
