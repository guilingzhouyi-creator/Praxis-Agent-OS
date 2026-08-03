"""Tests for tool_approval — Ring 3 approval/witness + human approval flow."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestRequestRing3Approval:
    """request_ring3_approval — initiates IPC cross-review."""

    def test_request_returns_dict(self):
        from tool_approval import request_ring3_approval
        r = request_ring3_approval("deploy", "agent-a", {"target": "server1"})
        assert isinstance(r, dict)
        assert "approved" in r
        assert "review_id" in r
        assert r["approved"] is False
        assert r.get("status") == "AWAITING"

    def test_request_with_empty_args(self):
        from tool_approval import request_ring3_approval
        r = request_ring3_approval("read_file", "agent-b", {})
        assert isinstance(r, dict)
        assert "review_id" in r

    def test_request_truncates_long_args(self):
        from tool_approval import request_ring3_approval
        long_val = "A" * 500
        r = request_ring3_approval("write", "agent-c", {"content": long_val})
        assert isinstance(r, dict)
        assert "review_id" in r


class TestCheckRing3Witness:
    """check_ring3_witness — polls for witness response."""

    def test_check_returns_dict(self):
        from tool_approval import check_ring3_witness
        r = check_ring3_witness("review-123", "agent-a")
        assert isinstance(r, dict)
        assert "approved" in r
        assert "review_id" in r

    def test_check_still_waiting(self):
        from tool_approval import check_ring3_witness
        r = check_ring3_witness("nonexistent", "agent-b")
        assert r.get("status") == "STILL_WAITING"
        assert r["approved"] is False

    def test_check_with_different_review_id(self):
        from tool_approval import check_ring3_witness
        r1 = check_ring3_witness("review-001", "agent-x")
        r2 = check_ring3_witness("review-999", "agent-y")
        assert r1["review_id"] != r2["review_id"]
