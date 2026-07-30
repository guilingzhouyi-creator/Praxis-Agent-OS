"""ToolSpec tests — spec validation, to_api_format, execute_tool_spec."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

RING_1 = "RING_1"
RING_2_5 = "RING_2_5"
RING_3 = "RING_3"


class TestToolSpec:
    """ToolSpec creation and basic properties."""

    def test_create_minimal_spec(self):
        from l3.tool_system.tool_spec import ToolSpec
        spec = ToolSpec(name="test_tool", description="Test tool",
                        category="general", ring=RING_1, danger=0)
        assert spec.name == "test_tool"
        assert spec.description == "Test tool"
        assert spec.ring == RING_1
        assert spec.danger == 0

    def test_create_with_all_fields(self):
        from l3.tool_system.tool_spec import ToolSpec, ParamSpec
        spec = ToolSpec(
            name="build", description="Build project",
            category="dev", ring=RING_2_5, danger=1,
            handler=lambda args, agent: {"success": True},
            parallel_safe=False, metadata={"timeout": 120},
        )
        assert spec.name == "build"
        assert spec.ring == RING_2_5
        assert spec.danger == 1
        assert callable(spec.handler)
        assert not spec.parallel_safe

    def test_validate_no_params(self):
        from l3.tool_system.tool_spec import ToolSpec
        spec = ToolSpec(name="test", description="x",
                        category="gen", ring=RING_1, danger=0)
        errors = spec.validate({})
        assert errors == []

    def test_validate_required_param_missing(self):
        from l3.tool_system.tool_spec import ToolSpec, ParamSpec
        spec = ToolSpec(name="test", description="x",
                        category="gen", ring=RING_1, danger=0,
                        parameters=[ParamSpec("path", "string", required=True)])
        errors = spec.validate({})
        assert any("path" in e for e in errors)

    def test_validate_type_mismatch(self):
        from l3.tool_system.tool_spec import ToolSpec, ParamSpec
        spec = ToolSpec(name="test", description="x",
                        category="gen", ring=RING_1, danger=0,
                        parameters=[ParamSpec("count", "int", required=True)])
        errors = spec.validate({"count": "not_an_int"})
        assert len(errors) > 0

    def test_validate_optional_param_omitted(self):
        from l3.tool_system.tool_spec import ToolSpec, ParamSpec
        spec = ToolSpec(name="test", description="x",
                        category="gen", ring=RING_1, danger=0,
                        parameters=[ParamSpec("path", "string", required=False)])
        errors = spec.validate({})
        assert errors == []

    def test_to_api_format(self):
        from l3.tool_system.tool_spec import ToolSpec, ParamSpec
        spec = ToolSpec(name="test", description="x",
                        category="gen", ring=RING_1, danger=0,
                        parameters=[ParamSpec("path", "string", required=True)])
        api = spec.to_api_format()
        assert api["function"]["name"] == "test"
        assert isinstance(api["function"]["parameters"], dict)

    def test_to_dict(self):
        from l3.tool_system.tool_spec import ToolSpec
        spec = ToolSpec(name="test", description="desc",
                        category="cat", ring=RING_1, danger=0)
        d = spec.to_dict()
        assert d["name"] == "test"
        assert d["ring"] == RING_1
        assert "handler" not in d


class TestToolRing:
    """ToolRing constants."""

    def test_ring_values(self):
        from l3.tool_system.tool_spec import ToolRing
        assert ToolRing.RING_1 == RING_1
        assert ToolRing.RING_2_5 == RING_2_5
        assert ToolRing.RING_3 == RING_3

    def test_ring_all_have_values(self):
        from l3.tool_system.tool_spec import ToolRing
        assert ToolRing.RING_1
        assert ToolRing.RING_2_5
        assert ToolRing.RING_3


class TestExecuteToolSpec:
    """execute_tool_spec basic error paths."""

    def test_unknown_tool_returns_error(self):
        from l3.tool_system.tool_spec import execute_tool_spec
        r = execute_tool_spec("__nonexistent__", {}, "test-agent")
        assert not r.get("success", True)
        assert "unknown tool" in r.get("error", "")

    def test_no_handler_returns_error(self):
        from l3.tool_system.tool_spec import execute_tool_spec
        from l3.tool_system.tool_spec import ToolSpec
        from l3.tool_system.tool_registry import register, reset_registry
        reset_registry()
        spec = ToolSpec(name="test_no_handler", description="x",
                        category="gen", ring=RING_1, danger=0)
        register(spec)
        r = execute_tool_spec("test_no_handler", {}, "test-agent")
        assert not r.get("success", True)
