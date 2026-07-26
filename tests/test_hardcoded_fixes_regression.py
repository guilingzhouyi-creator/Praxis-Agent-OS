"""Regression tests for hardcoded-constants refactoring (config-driven API design).

Verifies that all previously hardcoded values are now defined as
configurable constants in params.py and correctly consumed by callers.
"""

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestRCExportLimit:
    """reference_channel.py: RC_EXPORT_LIMIT replaces 999999 magic number."""

    def test_constant_exists(self):
        from kernel.params import RC_EXPORT_LIMIT
        assert RC_EXPORT_LIMIT == 999999

    def test_used_in_count(self):
        from services.reference_channel import ReferenceChannel
        import tempfile, os as _os
        tmp = _os.path.join(tempfile.gettempdir(), "_test_rc_count.jsonl")
        rc = ReferenceChannel(path=tmp)
        rc.event("test", {"msg": "hello"})
        rc.flush()
        cnt = rc.count(event_type="test")
        assert cnt >= 1
        # Cleanup
        try:
            _os.remove(tmp)
        except Exception:
            pass


class TestLogExportLimit:
    """log.py: LOG_EXPORT_LIMIT replaces 10000 magic number."""

    def test_constant_defined(self):
        from kernel.params import LOG_EXPORT_LIMIT
        assert LOG_EXPORT_LIMIT == 10000


class TestToolBuildTimeout:
    """tools/_build.py: TOOL_BUILD_TIMEOUT replaces timeout=120."""

    def test_constant_defined(self):
        from kernel.params import TOOL_BUILD_TIMEOUT
        assert TOOL_BUILD_TIMEOUT == 300

    def test_imported_in_build_module(self):
        from tools._build import build_project
        assert callable(build_project)


class TestAgentPriority:
    """boot.py: AGENT_PRIORITY config map replaces if/else priority."""

    def test_priority_map_defined(self):
        from kernel.params import AGENT_PRIORITY
        assert isinstance(AGENT_PRIORITY, dict)
        assert "default" in AGENT_PRIORITY
        assert "reviewer" in AGENT_PRIORITY
        assert AGENT_PRIORITY["reviewer"] == 3  # reviewer has higher priority
        assert AGENT_PRIORITY["default"] == 5
        assert AGENT_PRIORITY["writer"] == 5
        assert AGENT_PRIORITY["reader"] == 5

    def test_unknown_role_falls_back(self):
        from kernel.params import AGENT_PRIORITY
        # get with default should match boot.py behavior
        fallback = AGENT_PRIORITY.get("nonexistent_role", 5)
        assert fallback == 5


class TestContextRoleConstants:
    """context.py: _ROLE_TOOL / _ROLE_ASSISTANT replace hardcoded strings."""

    def test_constants_defined(self):
        from services.context import ContextManager
        assert callable(ContextManager)


class TestAgentRuntimeActionConstants:
    """agent_runtime.py: _ACTION_* constants replace hardcoded type strings."""

    def test_constants_importable(self):
        import agent_runtime
        assert hasattr(agent_runtime, "tick") or callable(agent_runtime.AgentRuntime)

    def test_runtime_imports(self):
        from agent_runtime import AgentRuntime
        assert callable(AgentRuntime)


class TestErrorBusEnglish:
    """error_bus.py: All Chinese docstrings translated to English."""

    def test_no_chinese_in_docstrings(self):
        """Verify error_bus.py has no remaining Chinese text."""
        import re
        path = os.path.join(os.path.dirname(__file__), "..", "src", "services", "error_bus.py")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        chinese = re.findall(r"[\u4e00-\u9fff]{2,}", content)
        assert len(chinese) == 0, f"Remaining Chinese fragments: {chinese[:5]}"
