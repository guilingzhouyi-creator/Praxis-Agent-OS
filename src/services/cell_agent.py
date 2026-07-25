"""Cell agent management — Agent registration/query/state operations.
Extracted from cell.py for modularity.
"""
from __future__ import annotations

import logging
from typing import Any

from kernel.params import DEFAULT_AGENT_CONFIGS
from .cell_types import AgentStatus, AgentInfo

logger = logging.getLogger(__name__)


def init_mailbox(self) -> None:
    """Initialize a mailbox dict for the cell, called by Cell.__init__."""
    self._mailbox: dict[str, list] = {}


def add_agent(self, agent_id: str, role: str = "",
              territory: list[str] | None = None,
              ring: int | None = None,
              max_scouts: int | None = None,
              auto_boot: bool = False) -> dict:
    """Register an agent in this Cell."""
    from .agent_terminal import get_terminal, TerminalCard, CardMode as TermCardMode, TerminalStatus
    with self._lock:
        if agent_id in self._agents:
            return {"success": False, "error": f"agent {agent_id} already registered"}
        defaults = DEFAULT_AGENT_CONFIGS.get(role) if role else None
        self._agents[agent_id] = AgentInfo(
            role=role,
            ring=ring or (defaults.ring if defaults else 1),
            territory=territory or [],
            max_concurrent_scouts=max_scouts or (defaults.max_scouts if defaults else 3),
        )
        self._mailbox[agent_id] = []
        logger.info("Cell %s: added %s (role=%s, ring=%d, scouts=%d)",
                    self.cell_id, agent_id, role or "(none)",
                    self._agents[agent_id].ring,
                    self._agents[agent_id].max_concurrent_scouts)
    if auto_boot:
        return _boot_agent(self, agent_id)
    return {"success": True}


def _boot_agent(self, agent_id: str) -> dict:
    """Boot an agent terminal if not already running."""
    from .agent_terminal import get_terminal, TerminalStatus
    with self._lock:
        info = self._agents.get(agent_id)
        if not info:
            return {"success": False, "error": f"agent {agent_id} not registered"}
    term = get_terminal(agent_id, role=info.role, territory=info.territory, cell_id=self.cell_id)
    if term.status in (TerminalStatus.BOOTING, TerminalStatus.STOPPED):
        term.boot()
    if term._tool_registry is None:
        _inject_tools(self, agent_id, term)
    return {"success": True}


def _ensure_terminal(self, aid: str, role: str, territory: list[str]) -> None:
    """Ensure an agent terminal exists and is booted."""
    from .agent_terminal import get_terminal, TerminalStatus
    from .tool_spec import TOOL_REGISTRY
    term = get_terminal(aid, role=role, territory=territory, cell_id=self.cell_id)
    if term.status in (TerminalStatus.BOOTING, TerminalStatus.STOPPED):
        term.boot()
    if term._tool_registry is None:
        term.set_tool_registry(TOOL_REGISTRY)
        term._tool_registry = TOOL_REGISTRY


def _inject_tools(self, agent_id: str, term: Any) -> None:
    """Inject TOOL_REGISTRY into an agent terminal."""
    from .tool_spec import TOOL_REGISTRY
    term.set_tool_registry(TOOL_REGISTRY)


def agent_status(self, agent_id: str) -> dict:
    """Get agent status from this Cell."""
    with self._lock:
        info = self._agents.get(agent_id)
        if not info:
            return {"success": False, "error": "unknown agent"}
        role_str = info.role if isinstance(info.role, str) else (
            info.role.name if hasattr(info.role, 'name') else str(info.role))
        return {
            "success": True, "agent_id": agent_id,
            "role": role_str,
            "ring": info.ring,
            "status": info.status.name if hasattr(info.status, 'name') else str(info.status),
            "territory": info.territory,
            "active_scouts": info.active_scouts,
            "max_concurrent_scouts": info.max_concurrent_scouts,
        }


def liveness(self) -> dict:
    """Check Cell and all agent terminals liveness."""
    from .agent_terminal import get_terminals
    terms = get_terminals()
    agent_results = {}
    healthy_count = 0
    total_count = 0
    with self._lock:
        agent_ids = list(self._agents.keys())
    for aid in agent_ids:
        total_count += 1
        term = terms.get(aid)
        if term is None:
            agent_results[aid] = {"status": "no_terminal", "alive": False}
        elif term.status.name in ("IDLE", "PROCESSING", "WAITING_SCOUT"):
            agent_results[aid] = {"status": term.status.name, "alive": True}
            healthy_count += 1
        elif term.status.name in ("BOOTING",):
            agent_results[aid] = {"status": "booting", "alive": True}
            healthy_count += 1
        else:
            agent_results[aid] = {"status": term.status.name, "alive": False}
    overall = "healthy" if healthy_count == total_count else "degraded" if healthy_count > 0 else "unreachable"
    return {
        "cell_id": self.cell_id, "overall": overall,
        "agents": agent_results, "healthy": healthy_count,
        "total": total_count, "territory": self.territory,
    }
