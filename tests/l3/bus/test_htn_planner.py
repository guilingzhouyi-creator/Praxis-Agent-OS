"""HTN Planner decomposition test — task decomposition + HTN service API."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestHTNInit:
    def test_get_service(self):
        from l3.htn_planner import get_service, reset_service
        reset_service()
        htn = get_service()
        assert htn is not None

    def test_decompose_simple(self):
        from l3.htn_planner import get_service, reset_service
        reset_service()
        htn = get_service()
        r = htn.decompose("read file README.md", domain=".")
        assert r is not None

    def test_decompose_empty(self):
        from l3.htn_planner import get_service, reset_service
        reset_service()
        htn = get_service()
        r = htn.decompose("", domain=".")
        assert r is not None

    def test_to_card(self):
        from l3.htn_planner import get_service, reset_service
        reset_service()
        htn = get_service()
        task = htn.decompose("list directory", domain=".")
        card = htn.to_card(task, domain=".")
        assert card is not None

    def test_known_tool_mappings(self):
        from l1.kernel.params.tool import HTN_DEFAULT_TOOLS
        assert isinstance(HTN_DEFAULT_TOOLS, dict)
        assert len(HTN_DEFAULT_TOOLS) > 0
        for key in ("analyze", "read", "write", "build", "test", "scout"):
            assert key in HTN_DEFAULT_TOOLS, f"missing HTN tool: {key}"
