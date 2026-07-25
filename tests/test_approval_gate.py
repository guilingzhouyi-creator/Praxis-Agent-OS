"""ApprovalGate tests — approval request lifecycle, approve/reject/timeout."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestApprovalGate:
    def test_get_threshold_default(self):
        from services.settings_center import get_center
        t = get_center().get_int("approval.danger_threshold", 3)
        assert isinstance(t, int)
        assert t >= 0

    def test_approval_request_create(self):
        from services.approval_gate import ApprovalRequest
        ar = ApprovalRequest(tool_name="deploy", agent_id="agent-a", reason="dangerous")
        assert ar.tool_name == "deploy"
        assert ar.agent_id == "agent-a"
        assert ar.status == "pending"

    def test_approve(self):
        from services.approval_gate import ApprovalRequest
        ar = ApprovalRequest(tool_name="delete", agent_id="agent-x")
        ar.approve("ok")
        assert ar.status == "approved"

    def test_reject(self):
        from services.approval_gate import ApprovalRequest
        ar = ApprovalRequest(tool_name="delete", agent_id="agent-x")
        ar.reject("not now")
        assert ar.status == "rejected"

    def test_wait_approved(self):
        from services.approval_gate import ApprovalRequest
        ar = ApprovalRequest(tool_name="deploy", agent_id="agent-a")
        ar.approve("go ahead")
        status = ar.wait(timeout=5)
        assert status == "approved"

    def test_wait_timeout(self):
        from services.approval_gate import ApprovalRequest
        ar = ApprovalRequest(tool_name="deploy", agent_id="agent-a")
        status = ar.wait(timeout=0.01)
        assert status == "timeout"
