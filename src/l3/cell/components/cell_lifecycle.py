"""Cell lifecycle mixin — boot/shutdown/emergency/reset/restart.

Extracted from cell/__init__.py to reduce the 1091-line Cell class."""

from __future__ import annotations

import logging
from collections.abc import Callable

from l1.kernel.params.system import CONTEXT_MAX_REGISTER_TOKENS, MEMORY_RESTORE_RING2_LIMIT
from l3.agent_terminal import get_terminals

logger = logging.getLogger(__name__)


class CellLifecycleMixin:
    """Mixin providing Cell lifecycle methods — boot, shutdown, restart, emergency."""

    # ── Lifecycle hooks ──

    def on_boot(self, hook: Callable) -> None:
        """Register a boot hook invoked before each agent boots."""
        if hook not in self._boot_hooks:
            self._boot_hooks.append(hook)

    def on_shutdown(self, hook: Callable) -> None:
        """Register a shutdown hook invoked before Cell shutdown."""
        if hook not in self._shutdown_hooks:
            self._shutdown_hooks.append(hook)

    def on_spawn(self, hook: Callable) -> None:
        """Register a spawn hook with optional veto power."""
        if hook not in self._spawn_hooks:
            self._spawn_hooks.append(hook)

    def on_kill(self, hook: Callable) -> None:
        """Register a kill hook with optional veto power."""
        if hook not in self._kill_hooks:
            self._kill_hooks.append(hook)

    # ── Agent boot / shutdown ──

    def boot_agent(self, agent_id: str) -> dict:
        """Boot (start) a specific agent terminal."""
        for hook in self._boot_hooks:
            try:
                hook(agent_id)
            except Exception as e:
                logger.warning("boot hook %s raised: %s", hook, e)
        self._pmu.increment("agent.boots")
        self._watchdog.register(agent_id)
        try:
            from l3.agent_terminal import get_terminal
            term = get_terminal(agent_id)
            if term:
                term.set_watchdog_pet(lambda aid: self._watchdog.pet(aid))
        except Exception as e:
            logger.warning("watchdog wire failed: %s", e)
        from l3.cell.components.cell_agent import _boot_agent
        return _boot_agent(self, agent_id)

    def boot_all(self) -> dict:
        """Boot all registered agents."""
        results = {}
        with self._lock:
            agent_ids = list(self._agents.keys())
        for aid in agent_ids:
            results[aid] = self.boot_agent(aid)
        self._watchdog.start()
        return {"success": all(r.get("success", False) for r in results.values()),
                "agents": results}

    def shutdown_all(self) -> dict:
        """Gracefully shut down all agents."""
        self._watchdog.stop()
        for hook in self._shutdown_hooks:
            try:
                hook()
            except Exception as e:
                logger.warning("shutdown hook %s raised: %s", hook, e)
        from l3.agent_terminal import reset_terminals
        reset_terminals()
        with self._lock:
            for info in self._agents.values():
                from l3.cell.components.cell_types import AgentStatus
                info.status = AgentStatus.IDLE
        return {"success": True}

    # ── Emergency stop & rollback ──

    def emergency_stop(self) -> dict:
        """Emergency stop — halt all agent activity."""
        with self._lock:
            self._emergency = True
            agent_ids = list(self._agents.keys())
        all_terms = get_terminals()
        paused = 0
        for aid in agent_ids:
            term = all_terms.get(aid)
            if term:
                try:
                    term.pause()
                    paused += 1
                except Exception as e:
                    logger.warning("Cell %s emergency_stop agent %s: %s", self.cell_id, aid, e)
        logger.warning("Cell %s EMERGENCY STOP: %d agents paused", self.cell_id, paused)
        return {"success": True, "cell_id": self.cell_id, "agents_paused": paused}

    def resume(self) -> dict:
        """Resume normal operation after emergency stop."""
        with self._lock:
            self._emergency = False
            agent_ids = list(self._agents.keys())
        all_terms = get_terminals()
        resumed = 0
        for aid in agent_ids:
            term = all_terms.get(aid)
            if term:
                try:
                    term.resume()
                    resumed += 1
                except Exception as e:
                    logger.warning("Cell %s resume agent %s: %s", self.cell_id, aid, e)
        logger.info("Cell %s resumed: %d agents", self.cell_id, resumed)
        return {"success": True, "cell_id": self.cell_id, "agents_resumed": resumed}

    # ── Context management ──

    def reset_agent_context(self, agent_id: str) -> dict:
        """Reset an agent's working context to combat context pollution."""
        term = get_terminals().get(agent_id)
        if not term:
            return {"success": False, "error": f"agent {agent_id} not found"}
        try:
            term.pause()
        except Exception as e:
            logger.warning("reset_agent_context pause failed: %s", e)
        try:
            from l3.memory.memory import get_memory
            mem = get_memory()
            mem.compact(agent_id)
            mem.forget_agent(agent_id)
            mem.restore(ring2_limit=MEMORY_RESTORE_RING2_LIMIT)
        except Exception as e:
            logger.warning("reset_agent_context memory reset failed: %s", e)
        try:
            term.resume()
        except Exception as e:
            logger.warning("reset_agent_context resume failed: %s", e)
        logger.info("Cell %s reset context for agent %s", self.cell_id, agent_id)
        return {"success": True, "cell_id": self.cell_id, "agent_id": agent_id, "action": "context_reset"}

    def restart_agent(self, agent_id: str) -> dict:
        """Restart an agent: shutdown terminal → clear memory → re-boot."""
        from ..agent_terminal import get_terminals
        with self._lock:
            if agent_id not in self._agents:
                return {"success": False, "error": f"agent {agent_id} not found"}
        term = get_terminals().get(agent_id)
        if term:
            term.shutdown()
        try:
            from l3.memory.memory import get_memory
            mem = get_memory()
            mem.forget_agent(agent_id)
            mem.compact(agent_id)
        except Exception as e:
            logger.warning("restart_agent memory clear: %s", e)
        try:
            from l3.memory.context_pool import unregister as _unreg
            _unreg(agent_id)
        except Exception as e:
            logger.warning("cell/restart_agent: %s", e)
        self._mmu.flush_agent(agent_id)
        try:
            from l3.memory.context_pool import register as _reg
            _reg(agent_id=agent_id, cell_id=self.cell_id, max_tokens=CONTEXT_MAX_REGISTER_TOKENS)
        except Exception as e:
            logger.warning("cell/restart_agent: %s", e)
        self.boot_agent(agent_id)
        logger.info("Cell %s restarted agent %s", self.cell_id, agent_id)
        return {"success": True, "agent_id": agent_id, "action": "restarted"}
