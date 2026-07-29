"""ToolSpec registration test — register/query/validate/serialize/mute"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestToolSpec:
    """ToolSpec basics"""

    def test_create(self):
        from l3.tool_system.tool_spec import ToolSpec, ParamSpec
        spec = ToolSpec(
            name="test_tool", description="A test",
            category="generic", ring="RING_1", danger=0,
            parameters=[ParamSpec("path", "string", required=True)],
        )
        assert spec.name == "test_tool"
        assert spec.ring == "RING_1"
        assert len(spec.parameters) == 1

    def test_auto_gates(self):
        from l3.tool_system.tool_spec import ToolSpec
        spec = ToolSpec(name="t", description="d", category="c", ring="RING_1", danger=0)
        assert len(spec.gates) >= 1
        assert "G1" in spec.gates

    def test_to_dict(self):
        from l3.tool_system.tool_spec import ToolSpec
        spec = ToolSpec(name="dict_tool", description="desc",
                        category="gen", ring="RING_1", danger=1)
        d = spec.to_dict()
        assert d["name"] == "dict_tool"
        assert d["danger"] == 1
        assert "gates" in d


class TestValidate:
    """Parameter validation"""

    def test_required_param_present(self):
        from l3.tool_system.tool_spec import ToolSpec, ParamSpec
        spec = ToolSpec(name="t", description="d", category="c", ring="RING_1", danger=0,
                        parameters=[ParamSpec("name", "string", required=True)])
        errs = spec.validate({"name": "hello"})
        assert len(errs) == 0

    def test_required_param_missing(self):
        from l3.tool_system.tool_spec import ToolSpec, ParamSpec
        spec = ToolSpec(name="t", description="d", category="c", ring="RING_1", danger=0,
                        parameters=[ParamSpec("name", "string", required=True)])
        errs = spec.validate({})
        assert len(errs) >= 1
        assert "missing" in errs[0]

    def test_optional_param(self):
        from l3.tool_system.tool_spec import ToolSpec, ParamSpec
        spec = ToolSpec(name="t", description="d", category="c", ring="RING_1", danger=0,
                        parameters=[ParamSpec("name", "string", required=False)])
        errs = spec.validate({})
        assert len(errs) == 0


class TestRegister:
    """Tool registration"""

    def setup_method(self):
        from l3.tool_system.tool_spec import clear_tools
        clear_tools()

    def test_register_and_get(self):
        from l3.tool_system.tool_spec import register, ToolSpec, TOOL_REGISTRY, clear_tools
        clear_tools()
        spec = ToolSpec(name="reg_tool", description="test", category="gen",
                        ring="RING_1", danger=0, handler=lambda a, b: {})
        register(spec)
        loaded = TOOL_REGISTRY.get("reg_tool")
        assert loaded is not None
        assert loaded.name == "reg_tool"

    def test_list_by_category(self):
        from l3.tool_system.tool_spec import register, ToolSpec, list_tools, clear_tools
        clear_tools()
        for i in range(3):
            register(ToolSpec(name=f"cat_tool_{i}", description="t", category="generic",
                              ring="RING_1", danger=0, handler=lambda a, b: {}))
        tools = list_tools(category="generic")
        assert len(tools) >= 3

    def test_list_by_ring(self):
        from l3.tool_system.tool_spec import register, ToolSpec, list_tools, clear_tools
        clear_tools()
        register(ToolSpec(name="ring2_tool", description="t", category="gen",
                          ring="RING_2_5", danger=1, handler=lambda a, b: {}))
        tools = list_tools(ring="RING_2_5")
        assert len(tools) >= 1

    def test_register_duplicate(self):
        from l3.tool_system.tool_spec import register, ToolSpec, TOOL_REGISTRY, clear_tools
        clear_tools()
        spec = ToolSpec(name="dup", description="d", category="c",
                        ring="RING_1", danger=0, handler=lambda a, b: {})
        register(spec)
        register(spec)  # should not raise
        count = sum(1 for n in TOOL_REGISTRY if n == "dup")
        assert count == 1


class TestExecute:
    """Tool execution"""

    def test_execute_success(self):
        from l3.tool_system.tool_spec import execute_tool, clear_tools
        clear_tools()
        recorded = []
        def handler(args, agent):
            recorded.append(args)
            return {"success": True, "data": "done"}
        from l3.tool_system.tool_spec import register, ToolSpec, ParamSpec
        register(ToolSpec(name="exec_tool", description="t", category="gen",
                          ring="RING_1", danger=0,
                          parameters=[ParamSpec("x", "string")],
                          handler=handler))
        r = execute_tool("exec_tool", {"x": "hello"}, "agent-a")
        assert r["success"]
        assert r["data"] == "done"

    def test_execute_unknown_tool(self):
        from l3.tool_system.tool_spec import execute_tool, clear_tools
        clear_tools()
        r = execute_tool("no_such_tool", {}, "agent-a")
        assert not r["success"]

    def test_execute_no_handler(self):
        from l3.tool_system.tool_spec import execute_tool, register, ToolSpec, clear_tools
        clear_tools()
        register(ToolSpec(name="no_handler", description="t", category="gen",
                          ring="RING_1", danger=0))
        r = execute_tool("no_handler", {}, "agent-a")
        assert not r["success"]


class TestMute:
    """Mute functionality"""

    def test_mute_tool(self):
        from l3.tool_system.tool_spec import mute_tool, is_muted, clear_mutes, clear_tools
        clear_mutes()
        clear_tools()
        mute_tool("some_tool")
        assert is_muted("some_tool") is True

    def test_unmute_tool(self):
        from l3.tool_system.tool_spec import mute_tool, unmute_tool, is_muted, clear_mutes, clear_tools
        clear_mutes()
        clear_tools()
        mute_tool("muted_tool")
        unmute_tool("muted_tool")
        assert is_muted("muted_tool") is False

    def test_is_muted_default(self):
        from l3.tool_system.tool_spec import is_muted, clear_mutes
        clear_mutes()
        assert is_muted("random_tool") is False
