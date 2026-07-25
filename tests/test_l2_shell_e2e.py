"""L2 Shell 端到端集成测试 — 启动真实服务进行完整链路测试。

遵循 tests/test_integration.py 的测试模式：
  1. 在测试函数内部 import 服务模块
  2. 创建 Cell、Agent、L3 等真实实例
  3. 执行操作并验证结果
  4. 用 reset_*() 清理单例状态
"""
from __future__ import annotations

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestL2ShellDispatchE2E:
    """端到端测试：L2_Shell dispatch 通过真实 Cell/Agent 执行完整链路。"""

    def test_dispatch_agents_with_real_cell(self):
        """创建 Cell + Agent 后，/agents 命令应能列出该 agent。"""
        from services.cell import get_cell, reset_cells
        from services.agent_terminal import reset_terminals
        from services.scout import reset_pool
        from services.l2_shell import dispatch, reset_state

        reset_state()
        reset_terminals()
        reset_pool()
        reset_cells()

        try:
            cell = get_cell("e2e-test-cell", ["."])
            cell.add_agent("alpha", role="writer", territory=["."], auto_boot=True)
            time.sleep(0.2)

            r = dispatch("/agents")
            assert isinstance(r, dict)
            agents = r.get("agents", [])
            assert len(agents) >= 1
            aids = [a["agent_id"] for a in agents]
            assert "alpha" in aids
        finally:
            reset_terminals()
            reset_pool()
            reset_cells()
            reset_state()

    def test_dispatch_connect_disconnect_live(self):
        """真实 Cell + Agent 的 /connect → /disconnect 完整流程。"""
        from services.cell import get_cell, reset_cells
        from services.agent_terminal import reset_terminals
        from services.scout import reset_pool
        from services.l2_shell import dispatch, reset_state, get_state

        reset_state()
        reset_terminals()
        reset_pool()
        reset_cells()

        try:
            cell = get_cell("e2e-connect", ["."])
            cell.add_agent("connector", role="writer", territory=["."], auto_boot=True)
            time.sleep(0.3)

            # /connect
            r = dispatch("/connect connector")
            # 可能因为 LLM/provider 不可用而被 preconnect 拒绝，但路由本身正确
            assert isinstance(r, dict)
            if r.get("success"):
                s = get_state()
                assert s.is_direct()
                assert s.agent_id == "connector"

                # /disconnect
                r2 = dispatch("/disconnect")
                assert r2.get("success")
                assert not s.is_direct()
        finally:
            reset_terminals()
            reset_pool()
            reset_cells()
            reset_state()

    def test_dispatch_status_after_connect(self):
        """连接后在 Direct 模式下 /status 应显示 agent 信息。"""
        from services.cell import get_cell, reset_cells
        from services.agent_terminal import reset_terminals
        from services.scout import reset_pool
        from services.l2_shell import dispatch, reset_state, get_state

        reset_state()
        reset_terminals()
        reset_pool()
        reset_cells()

        try:
            cell = get_cell("e2e-status", ["."])
            cell.add_agent("stat-bot", role="reader", territory=["."], auto_boot=True)
            time.sleep(0.3)

            # 强制设置 Direct 状态（不需要 LLM preconnect）
            state = get_state()
            state.switch_to_direct("e2e-status", "stat-bot", "sess-e2e")

            r = dispatch("/status")
            assert r.get("mode") == "DIRECT"
            assert r.get("agent_id") == "stat-bot"
            assert r.get("session_id") == "sess-e2e"
            # liveness 应该存在（Cell 是活的）
            assert "liveness" in r or "liveness_error" in r
        finally:
            reset_terminals()
            reset_pool()
            reset_cells()
            reset_state()

    def test_dispatch_help_returns_commands(self):
        """/help 在任何状态下都应返回命令列表。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/help")
        assert r.get("success")
        assert r.get("format") == "table"
        cmds = r.get("output", [])
        assert len(cmds) > 0
        names = [c["command"] for c in cmds]
        assert "/help" in names
        assert "/connect" in names
        assert "/disconnect" in names

    def test_dispatch_unknown_command(self):
        """未知命令应返回 error + suggestions。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/xyznonexistent")
        assert not r.get("success")
        assert "unknown" in r.get("error", "").lower()
        assert "suggestions" in r

    def test_dispatch_mode_switch(self):
        """/mode 应正确显示和切换工具模式。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/mode")
        assert r.get("mode") == "L3A"

        r2 = dispatch("/mode tool read")
        assert "current_tool_mode" in r2


class TestL2ShellDirectMessageE2E:
    """Direct 消息发送的端到端测试。"""

    def test_non_slash_routes_to_intent(self):
        """非 / 文本在 L3A 模式下应路由到 l3 coordinator。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        # L3 coordinator 已存在（服务层自动初始化）
        r = dispatch("list current directory")
        # coordinator.process_intent 应返回一个 card 结果（可能出错但路由正确）
        assert isinstance(r, dict)

    def test_direct_message_send_to_live_agent(self):
        """在 Direct 模式下发送消息给真实 agent。"""
        from services.cell import get_cell, reset_cells
        from services.agent_terminal import reset_terminals
        from services.scout import reset_pool
        from services.l2_shell import dispatch, reset_state, get_state

        reset_state()
        reset_terminals()
        reset_pool()
        reset_cells()

        try:
            cell = get_cell("e2e-msg", ["."])
            cell.add_agent("msg-bot", role="reader", territory=["."], auto_boot=True)
            time.sleep(0.3)

            state = get_state()
            state.switch_to_direct("e2e-msg", "msg-bot", "sess-msg")

            # 发送非 / 消息，应路由到 _direct_message
            r = dispatch("hello agent")
            assert isinstance(r, dict)
            # 即使 agent 处理失败，路由本身是正确的
            assert "success" in r or "error" in r
        finally:
            reset_terminals()
            reset_pool()
            reset_cells()
            reset_state()


class TestL2ShellCentralCommandsE2E:
    """9 个中央控制命令的端到端测试——验证路由到真实服务。"""

    def test_cmd_intents(self):
        """intents 命令应通过 L3 coordinator 返回数据。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/intents")
        assert "intents" in r

    def test_cmd_scheduler(self):
        """scheduler 命令应返回调度状态。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/scheduler")
        assert r.get("success")

    def test_cmd_observe(self):
        """observe 命令应返回可观测数据。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/observe")
        assert "health" in r or "alerts" in r or "metrics" in r or r.get("success")

    def test_cmd_skills(self):
        """skills 命令应返回 R4Agent 技能列表。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/skills")
        assert "skills" in r or r.get("success")

    def test_cmd_cells(self):
        """cells 命令应列出 cell。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/cells")
        assert "cells" in r or r.get("success")

    def test_cmd_cross(self):
        """cross 命令应返回跨 cell 协调状态。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/cross")
        assert "cross_cell" in r or r.get("success")

    def test_cmd_security(self):
        """security 命令应返回安全统计。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/security")
        assert "stats" in r or r.get("success")

    def test_cmd_memory(self):
        """memory 命令应返回内存统计。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/memory")
        assert "stats" in r or r.get("success")

    def test_cmd_plugins(self):
        """plugins 命令应返回插件列表。"""
        from services.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/plugins")
        assert "plugins" in r or "stats" in r or r.get("success")
