"""Phase 5 integration tests — Skill expansion + Middleware + Persistence + SubAgent tool."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ── Skill expansion (allowed_tools, variables, expand, update) ──

class TestSkillExpand:
    def test_skill_create_with_allowed_tools(self):
        from l1.kernel.skill import Skill
        s = Skill(name="reviewer", allowed_tools=["read_file", "grep"])
        assert s.allowed_tools == ["read_file", "grep"]
        d = s.to_dict()
        assert d["allowed_tools"] == ["read_file", "grep"]
        assert d["variables"] == []

    def test_skill_expand_variables(self):
        from l1.kernel.skill import Skill
        s = Skill(name="deploy", prompt="Deploy $TARGET to $ENV")
        expanded = s.expand(TARGET="app", ENV="staging")
        assert expanded == "Deploy app to staging"

    def test_skill_expand_no_prompt(self):
        from l1.kernel.skill import Skill
        s = Skill(name="empty")
        assert s.expand(TARGET="x") == ""

    def test_skill_expand_missing_var_leaves_placeholder(self):
        from l1.kernel.skill import Skill
        s = Skill(name="partial", prompt="Hello $NAME, your $TOKEN")
        r = s.expand(NAME="world")
        assert "world" in r
        assert "$TOKEN" in r

    def test_skill_update_existing(self):
        from l1.kernel.skill import SkillManager, reset_skill_manager
        reset_skill_manager()
        sm = SkillManager()
        sm.register("test", {"name": "test", "description": "original"})
        r = sm.update("test", {"description": "updated"})
        assert r["success"]
        assert sm.get("test")["description"] == "updated"

    def test_skill_update_missing(self):
        from l1.kernel.skill import SkillManager, reset_skill_manager
        reset_skill_manager()
        sm = SkillManager()
        r = sm.update("nonexistent", {"x": 1})
        assert not r["success"]
        assert "not found" in r["error"]

    def test_list_by_allowed_tools_none(self):
        from l1.kernel.skill import SkillManager, reset_skill_manager
        reset_skill_manager()
        sm = SkillManager()
        sm.register("reviewer", {"name": "reviewer", "allowed_tools": None})
        sm.register("deployer", {"name": "deployer", "allowed_tools": ["bash", "write_file"]})
        results = sm.list_by_allowed_tools("read_file")
        assert len(results) == 1
        assert results[0]["name"] == "reviewer"

    def test_list_by_allowed_tools_match(self):
        from l1.kernel.skill import SkillManager, reset_skill_manager
        reset_skill_manager()
        sm = SkillManager()
        sm.register("reviewer", {"name": "reviewer", "allowed_tools": ["read_file", "grep"]})
        sm.register("deployer", {"name": "deployer", "allowed_tools": ["bash"]})
        results = sm.list_by_allowed_tools("read_file")
        assert len(results) == 1
        assert results[0]["name"] == "reviewer"

    def test_skill_to_dict_roundtrip(self):
        from l1.kernel.skill import Skill
        s = Skill(
            name="test",
            description="test skill",
            rules=["DO: be good"],
            procedures=[{"step": "check"}],
            knowledge={"key": "val"},
            allowed_tools=["read_file"],
            variables=["TARGET"],
            prompt="Do $TARGET",
        )
        d = s.to_dict()
        assert d["name"] == "test"
        assert d["allowed_tools"] == ["read_file"]
        assert d["variables"] == ["TARGET"]
        assert d["prompt"] == "Do $TARGET"
        assert d["rules"] == 1
        assert d["procedures"] == 1


# ── Middleware chain (ConfineMiddleware, BeforeOutcome) ──

class TestMiddlewareChain:
    def test_confine_proceed_no_roots(self):
        from l3.services.middleware import BeforeOutcome, ConfineMiddleware
        mw = ConfineMiddleware()
        out = mw.before("read_file", {"path": "/etc/passwd"}, "agent")
        assert out == BeforeOutcome.PROCEED

    def test_confine_blocks_outside_root(self):
        from l3.services.middleware import BeforeOutcome, ConfineMiddleware
        mw = ConfineMiddleware(allowed_roots=["/safe/area"])
        out = mw.before("read_file", {"path": "/etc/passwd"}, "agent")
        assert out == BeforeOutcome.DENY

    def test_confine_allows_inside_root(self):
        from l3.services.middleware import BeforeOutcome, ConfineMiddleware
        mw = ConfineMiddleware(allowed_roots=["/safe/area"])
        out = mw.before("read_file", {"path": "/safe/area/file.txt"}, "agent")
        assert out == BeforeOutcome.PROCEED

    def test_confine_no_path_arg(self):
        from l3.services.middleware import BeforeOutcome, ConfineMiddleware
        mw = ConfineMiddleware(allowed_roots=["/safe"])
        out = mw.before("list_dir", {"pattern": "*.py"}, "agent")
        assert out == BeforeOutcome.PROCEED

    def test_confine_target_key(self):
        from l3.services.middleware import BeforeOutcome, ConfineMiddleware
        mw = ConfineMiddleware(allowed_roots=["/safe"])
        out = mw.before("write_file", {"target": "/bad/place"}, "agent")
        assert out == BeforeOutcome.DENY

    def test_middleware_chain_all_proceed(self):
        from l3.services.middleware import (
            BeforeOutcome,
            ConfineMiddleware,
            MiddlewareChain,
        )
        chain = MiddlewareChain()
        chain.add(ConfineMiddleware(allowed_roots=["/safe"]))
        chain.add(ConfineMiddleware())
        chain.add(ArgRepairMiddleware())
        out = chain.before("read_file", {"path": "/safe/x"}, "agent")
        assert out == BeforeOutcome.PROCEED

    def test_middleware_chain_deny_stops(self):
        from l3.services.middleware import (
            BeforeOutcome,
            ConfineMiddleware,
            MiddlewareChain,
        )
        chain = MiddlewareChain()
        chain.add(ConfineMiddleware(allowed_roots=["/safe"]))
        out = chain.before("read_file", {"path": "/etc/hosts"}, "agent")
        assert out == BeforeOutcome.DENY

    def test_after_proceed_default(self):
        from l3.services.middleware import AfterOutcome, ToolMiddleware
        mw = ToolMiddleware()
        out = mw.after("read_file", {"result": "ok"}, "agent")
        assert out == AfterOutcome.PROCEED

    def test_arg_repair_whitespace(self):
        from l3.services.middleware import ArgRepairMiddleware, BeforeOutcome
        mw = ArgRepairMiddleware()
        args = {"path": "  /tmp/x  "}
        out = mw.before("read_file", args, "agent")
        assert out == BeforeOutcome.PROCEED
        assert args["path"] == "/tmp/x"

    def test_arg_repair_bool_strings(self):
        from l3.services.middleware import ArgRepairMiddleware
        mw = ArgRepairMiddleware()
        args = {"recursive": "true", "force": "false"}
        mw.before("rm", args, "agent")
        assert args["recursive"] is True
        assert args["force"] is False


# ── Persistence recall (save_snapshot + append_transcript + search_transcript + recall) ──

class TestPersistenceRecall:
    def test_save_and_recall_transcript(self):
        """Save snapshot + transcript, then recall by keyword."""
        td = tempfile.mkdtemp()
        old_data_dir = os.environ.get("PRAXIS_DATA_DIR")
        os.environ["PRAXIS_DATA_DIR"] = td
        try:
            from l3.agent.agent_persist import append_transcript, recall, save_snapshot
            aid = "phase5-test-agent"
            save_snapshot(aid, {"status": True, "summary": "initial state"})
            append_transcript(aid, {"role": "user", "content": "hello world"})
            r = recall({"query": "hello", "limit": 10}, aid)
            assert r["success"]
            assert r["count"] >= 1
            assert all("content" in x for x in r["results"])
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)
            if old_data_dir is None:
                del os.environ["PRAXIS_DATA_DIR"]
            else:
                os.environ["PRAXIS_DATA_DIR"] = old_data_dir


# ── SubAgent tool ──

class TestSubAgentTool:
    def test_subagent_tool_unknown_mode(self):
        from l3.tools._subagent import subagent_tool
        r = subagent_tool({"mode": "invalid", "task": "x"}, "agent")
        assert not r["success"]
        assert "unknown mode" in r["error"]

    def test_subagent_tool_no_task(self, mocker):
        from l3.tools._subagent import subagent_tool
        mocker.patch("l3.subagent.SubAgent.run", return_value=mocker.Mock(
            success=False, findings=[], error="no task", elapsed=0.0))
        r = subagent_tool({"mode": "review"}, "agent")
        assert not r["success"]

    def test_subagent_tool_review_sync(self, mocker):
        from l3.tools._subagent import subagent_tool
        mock_result = mocker.Mock()
        mock_result.success = True
        mock_result.findings = []
        mock_result.error = ""
        mocker.patch("l3.subagent.SubAgent.run", return_value=mock_result)
        r = subagent_tool({"mode": "review", "task": "check file"}, "agent")
        assert r["success"]

    def test_subagent_tool_valid_modes(self):
        from l3.tools._subagent import _PROFILES
        assert "review" in _PROFILES
        assert "deploy" in _PROFILES
        assert "scout" in _PROFILES
        assert _PROFILES["review"]["read_only"]
        assert not _PROFILES["deploy"]["read_only"]

    def test_profile_tool_sets(self):
        from l3.tools._subagent import _PROFILES
        review_tools = _PROFILES["review"]["allowed_tools"]
        assert "read_file" in review_tools
        assert "bash" not in review_tools


# Helper for middleware test that references ArgRepairMiddleware midway
from l3.services.middleware import ArgRepairMiddleware
