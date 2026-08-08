"""CellCoreMixin — agent registry, skill binding, state, and memory policy.

Holds the Cell's core business logic: agent add/remove, skill white-listing,
attack-team activation, state persistence, and the deliberation memory
policy switch. The Cell class composes this mixin (see ``cell/__init__.py``).
"""

from __future__ import annotations

import logging
from typing import Any

from l1.kernel.params.agent import (
    DEFAULT_AGENT_CONFIGS,
    DEFAULT_AGENT_RING,
    DEFAULT_MAX_CONCURRENT_SCOUTS,
)
from l2.i18n import t as _t

from .cell_types import AgentInfo, MessageType

logger = logging.getLogger(__name__)


class CellCoreMixin:
    """Cell core: agent registry, skills, attack team, state, memory policy."""

    def add_agent(
        self,
        agent_id: str,
        role: str = "",
        territory: list[str] | None = None,
        ring: int | None = None,
        max_scouts: int | None = None,
        model_config: dict | None = None,
        auto_boot: bool = True,
    ) -> dict:
        """Register a new agent in this Cell."""
        defaults = DEFAULT_AGENT_CONFIGS.get(role) if role else None
        info = AgentInfo(
            role=role,
            ring=ring or (defaults.ring if defaults else DEFAULT_AGENT_RING),
            territory=territory or [],
            max_concurrent_scouts=max_scouts or (defaults.max_scouts if defaults else DEFAULT_MAX_CONCURRENT_SCOUTS),
        )
        # Apply model_config: param overrides defaults, overrides registry
        if model_config:
            info.model_config = model_config
        elif defaults and defaults.model_config:
            info.model_config = dict(defaults.model_config)
        else:
            # Resolve from ThinkQuotaRegistry for this agent
            from l3.scheduler.think_registry import get_think_registry

            reg = get_think_registry()
            active = max(1, len([a for a in self._agents.values() if a.status.name in ("IDLE", "RUNNING")]))
            resolved = reg.resolve(self.cell_id, agent_id, active_agents=active, agent_model_config=info.model_config)
            if resolved:
                info.model_config = resolved
        # Spawn hooks — may veto by returning {"success": False, ...}.
        for hook in self._spawn_hooks:
            try:
                vr = hook(agent_id, role, territory, ring)
                if isinstance(vr, dict) and not vr.get("success", True):
                    return {
                        "success": False,
                        "error": _t("core.spawn_vetoed", reason=vr.get("error", "?")),
                        "hook_error": vr,
                    }
            except Exception as e:
                logger.warning("spawn hook %s raised: %s", hook, e)
        with self._lock:
            if agent_id in self._agents:
                return {
                    "success": False,
                    "error": _t("core.agent_already_registered", agent_id=agent_id),
                }
            self._agents[agent_id] = info
            self._mailbox[agent_id] = []
        # Warm MMU TLB with the new agent's territory mappings
        self._mmu.warm_from_agents(self._agents)
        if auto_boot:
            return self.boot_agent(agent_id)
        return {"success": True}

    def remove_agent(self, agent_id: str) -> dict:
        """Remove an agent from the Cell.

        Shuts down the agent terminal, unregisters from mailbox and process table.
        Used by CentralController._process_admin_card (kill_agent).
        """
        # Kill hooks — may veto by returning {"success": False, ...}.
        for hook in self._kill_hooks:
            try:
                vr = hook(agent_id)
                if isinstance(vr, dict) and not vr.get("success", True):
                    return {
                        "success": False,
                        "error": _t("core.kill_vetoed", reason=vr.get("error", "?")),
                        "hook_error": vr,
                    }
            except Exception as e:
                logger.warning("kill hook %s raised: %s", hook, e)
        from l3.agent_terminal import get_terminals

        with self._lock:
            if agent_id not in self._agents:
                return {
                    "success": False,
                    "error": _t("core.agent_not_found", agent_id=agent_id),
                }
            del self._agents[agent_id]
            self._mailbox.pop(agent_id, None)
            self._watchdog.unregister(agent_id)
            self._mmu.flush_agent(agent_id)
        try:
            term = get_terminals().get(agent_id)
            if term:
                term.shutdown()
        except Exception as e:
            logger.warning("cell/__init__: %s", e)
        try:
            from l3.memory.context_pool import unregister as _unregister_cp

            _unregister_cp(agent_id)
            from l3.memory.memory import get_memory

            get_memory().forget_agent(agent_id)
        except Exception as e:
            logger.warning("cell/__init__: %s", e)
        # Emit cell bus event for sandbox _path_index cleanup
        try:
            self._cell_bus.emit("cell.agent_removed", {"agent_id": agent_id, "cell_id": self.cell_id})
        except Exception as e:
            logger.warning("cell/__init__: %s", e)
        return {"success": True, "agent_id": agent_id, "action": "removed"}

    # ══ Skill binding (回灌到 Cell) ══

    def bind_skills(self, names: list[str] | None = None) -> dict:
        """Bind a white-list of skills to this Cell.

        Bound skills are injected into this Cell's agents (see
        AgentLoop._inject_extra_context).  When the list is empty the Cell
        falls back to the global skill pool (backward compatible).

        Args:
            names: Skill names to allow; ``None``/empty clears bindings.

        Returns:
            {"success": bool, "bound": int, "cell_id": str}
        """
        from l1.kernel.skill import get_skill_manager

        sm = get_skill_manager()
        bound = 0
        failed: list[str] = []
        for name in names or []:
            r = sm.bind_skill(self.cell_id, name)
            if r.get("success"):
                bound += 1
            else:
                failed.append(name)
        return {"success": True, "cell_id": self.cell_id, "bound": bound, "failed": failed}

    def skills(self) -> set[str]:
        """Return the skill white-list bound to this Cell (empty = global pool)."""
        from l1.kernel.skill import get_skill_manager

        return get_skill_manager().skills_for_cell(self.cell_id)

    # ══ Security-team activation (attack posture) ══

    def activate_attack_team(self) -> dict:
        """Activate the security-team binding for attack posture.

        Reads ``team.attack.domains`` (SettingsCenter; default empty) and for
        each configured domain creates one peer agent (``agent-<domain>``)
        bound to that domain's skill white-list. Offensive skills stay dormant
        until the system posture is full-power attack (constitution §9.2 +
        AgentLoop posture gate + use_skill gate), so activating the team is
        harmless in productive posture. Empty config = no attack capability.

        Returns:
            {"success": bool, "created": [agent ids], "bound": int,
             "failed": [skill names], "domains": [...]}
        """
        from l1.kernel.params.system import TEAM_ATTACK_DOMAINS

        try:
            from l3.config.settings_center import get_center

            domains = get_center().get("team.attack.domains", None)
        except Exception:
            domains = None
        domains = domains if isinstance(domains, dict) else TEAM_ATTACK_DOMAINS
        created: list[str] = []
        bound = 0
        failed: list[str] = []
        for domain, skills in domains.items():
            agent_id = f"agent-{domain}"
            if agent_id not in self._agents:
                r = self.add_agent(agent_id, role=domain, territory=[domain], auto_boot=True)
                # Only report/bind agents actually registered — a spawn-hook
                # veto returns success=False BEFORE registration.
                if not r.get("success"):
                    failed.append(agent_id)
                    continue
                created.append(agent_id)
            if skills:
                br = self.bind_skills([s for s in skills if isinstance(s, str)])
                bound += br.get("bound", 0)
                failed += br.get("failed", [])
        # P1: record attack-team activation in StatsCenter.
        try:
            from l3.tool_system.security_mode import ingest_security_metric

            ingest_security_metric(
                "security.team.activated",
                value=float(len(created)),
                tags={"domains": ",".join(created)},
            )
        except Exception:
            pass
        return {"success": True, "created": created, "bound": bound, "failed": failed, "domains": list(domains.keys())}

    # ══ Cell state persistence ══

    def save_state(self, path: str = "") -> dict:
        """Persist Cell state to disk."""
        from l3.cell.components.cell_state import save_state as _save

        return _save(self, path)

    def restore_state(self, path: str = "") -> dict:
        """Restore Cell state from disk."""
        from l3.cell.components.cell_state import restore_state as _restore

        return _restore(self, path)

    # ── Memory policy engine (deliberation isolation) ──

    def set_memory_policy(self, policy: str) -> None:
        """Switch the Cell memory policy.

        isolated     — default: Peer Agents' R1-R3 stays agent-isolated
        deliberation — L3A conference mode: Cell's shared ring is activated
                       for the convention (convene() sets, close_convention()
                       restores)
        """
        from l1.kernel.params.agent import (
            CELL_MEMORY_POLICY_DELIBERATION,
            CELL_MEMORY_POLICY_ISOLATED,
        )

        if policy not in (CELL_MEMORY_POLICY_ISOLATED, CELL_MEMORY_POLICY_DELIBERATION):
            logger.warning("cell %s: unknown memory policy %r", self.cell_id, policy)
            return
        old = self._memory_policy
        self._memory_policy = policy
        if policy == CELL_MEMORY_POLICY_DELIBERATION:
            from l3.memory.central_memory import get_cell_memory

            self._convention_memory = get_cell_memory(self.cell_id)
        else:
            self._convention_memory = None
        logger.info("cell %s: memory policy %s → %s", self.cell_id, old, policy)

    def get_memory_policy(self) -> str:
        return self._memory_policy

    def convention_memory(self) -> Any | None:
        """Return the Cell's shared deliberation memory ring.

        Strategy guard: returns None unless the Cell is in deliberation
        (conference) mode — the shared ring is NOT accessible in isolated
        (default) mode. Peer Agents' negotiation context lives here during
        a convention; outside conventions each agent keeps isolated memory.
        """
        if self._memory_policy == "deliberation":
            return self._convention_memory
        return None

    def close_convention(self, issue_card_id: str) -> dict:
        """Close the currently active convention."""
        from l3.cell.components.cell_convention import close_convention as _close

        return _close(self, issue_card_id)

    def handle_convention_message(self, agent_id: str, msg_type: MessageType, payload: dict) -> dict:
        """Process a message for the active convention."""
        from l3.cell.components.cell_convention import handle_convention_message as _handle

        return _handle(self, agent_id, msg_type, payload)
