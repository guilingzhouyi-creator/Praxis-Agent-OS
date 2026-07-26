"""Agent Control Block — OS Process Control Block equivalent for Agent OS.

Design:
  1. Slot-based — each agent has named slots, not a fixed struct
  2. Extensible — external modules can register custom slot types
  3. Versioned — each slot carries a version number for migration
  4. Observable — slot changes emit events for listeners
  5. Serializable — JSON serializable, supports persistence

Usage:
    acb = AgentControlBlock("agent_b")
    acb.set("statecharts", {"task": "EXECUTING", "health": "HEALTHY"})
    acb.set("reputation", 0.92)
    acb.on_change("reputation", lambda v: print(f"reputation changed: {v}"))
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from services._base import BaseService
from kernel.params.system import DEFAULT_TOKEN_BUDGET

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# Slot system
# ═════════════════════════════════════════════════════════════════════════════

# Slot registry — external modules can register custom slot types
_slot_registry: dict[str, dict] = {}


def register_slot(slot_name: str, default: Any = None, description: str = "",
                  version: int = 1, validator: Callable | None = None) -> None:
    """Register a slot type. External modules can extend."""
    _slot_registry[slot_name] = {
        "default": default, "description": description,
        "version": version, "validator": validator,
    }


@dataclass
class SlotEntry:
    name: str
    value: Any
    version: int = 1
    updated_at: float = field(default_factory=time.time)
    updated_by: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name, "value": self.value,
            "version": self.version, "updated_at": self.updated_at,
        }


# ═════════════════════════════════════════════════════════════════════════════
# AgentControlBlock
# ═════════════════════════════════════════════════════════════════════════════

class AgentControlBlock:
    """Agent Control Block — extensible slot container.

    Each agent has an ACB, which is a set of named slots.
    Slots can be added dynamically without a fixed structure.
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._slots: dict[str, SlotEntry] = {}
        self._lock = threading.RLock()
        self._listeners: dict[str, list[Callable]] = {}
        self._global_listeners: list[Callable] = []
        self.created_at = time.time()

        # Initialize default slots
        self._init_defaults()

    def _init_defaults(self) -> None:
        """Load default slots from registry."""
        for name, meta in _slot_registry.items():
            if meta["default"] is not None:
                self._slots[name] = SlotEntry(name=name, value=meta["default"],
                                               version=meta["version"])

    # ── Basic CRUD ──

    def get(self, name: str, default: Any = None) -> Any:
        """Read a slot value."""
        with self._lock:
            entry = self._slots.get(name)
            if entry is None:
                return default
            return entry.value

    def set(self, name: str, value: Any, source: str = "") -> dict:
        """Set a slot value. Triggers listeners."""
        meta = _slot_registry.get(name, {})
        # Validate
        validator = meta.get("validator")
        if validator:
            err = validator(value)
            if err:
                return {"success": False, "error": str(err)}

        with self._lock:
            old = self._slots.get(name)
            entry = SlotEntry(name=name, value=value,
                              version=old.version + 1 if old else meta.get("version", 1),
                              updated_by=source)
            self._slots[name] = entry

        # Trigger listeners
        self._notify(name, value, old.value if old else None)
        return {"success": True, "slot": name, "value": value, "version": entry.version}

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._slots

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._slots.keys())

    def delete(self, name: str) -> bool:
        with self._lock:
            if name in self._slots:
                del self._slots[name]
                return True
            return False

    def to_dict(self) -> dict:
        """Serialize the entire ACB."""
        with self._lock:
            return {
                "agent_id": self.agent_id,
                "created_at": self.created_at,
                "slots": {n: s.to_dict() for n, s in self._slots.items()},
            }

    @classmethod
    def from_dict(cls, data: dict) -> AgentControlBlock:
        """Deserialize from dict."""
        acb = cls(data["agent_id"])
        acb.created_at = data.get("created_at", time.time())
        for name, sdata in data.get("slots", {}).items():
            acb._slots[name] = SlotEntry(
                name=sdata["name"], value=sdata["value"],
                version=sdata.get("version", 1),
                updated_at=sdata.get("updated_at", 0),
                updated_by=sdata.get("updated_by", ""),
            )
        return acb

    # ── Observer pattern ──

    def on_change(self, slot_name: str, callback: Callable[[Any], None]) -> None:
        """Register a slot change listener."""
        with self._lock:
            self._listeners.setdefault(slot_name, []).append(callback)

    def on_any_change(self, callback: Callable) -> None:
        """Register a global change listener."""
        with self._lock:
            self._global_listeners.append(callback)

    def _notify(self, name: str, new: Any, old: Any) -> None:
        for cb in self._listeners.get(name, []):
            try:
                cb(new)
            except Exception as e:
                logger.warning("acb handler: %s", e)
        for cb in self._global_listeners:
            try:
                cb({"agent_id": self.agent_id, "slot": name, "old": old, "new": new})
            except Exception as e:
                logger.warning("acb handler: %s", e)

    # ── Snapshot & restore ──

    def snapshot(self) -> dict:
        """Current state snapshot (for Statecharts integration)."""
        return {
            "agent_id": self.agent_id,
            "statecharts": {
                "task": self.get("task_state", "IDLE"),
                "health": self.get("health_state", "HEALTHY"),
            },
            "reputation": self.get("reputation", 0.85),
            "token_usage": f'{self.get("token_consumed", 0)}/{self.get("token_budget", DEFAULT_TOKEN_BUDGET)}',
            "current_card": self.get("current_card", ""),
            "uptime": time.time() - self.created_at,
        }

    def __repr__(self) -> str:
        return f"ACB({self.agent_id}: {len(self._slots)} slots)"


# ═════════════════════════════════════════════════════════════════════════════
# ACB service
# ═════════════════════════════════════════════════════════════════════════════

class ACBService(BaseService):
    """ACB management service — manages all Agent ACB lifecycles."""

    def __init__(self):
        super().__init__("acb")
        self._agents: dict[str, AgentControlBlock] = {}
        self._lock = threading.RLock()

    def _on_start(self) -> dict:
        return {"success": True, "agents": 0}

    def _on_stop(self) -> dict:
        with self._lock:
            self._agents.clear()
        return {"success": True}

    def create(self, agent_id: str) -> dict:
        """Create a new ACB for an agent."""
        with self._lock:
            if agent_id in self._agents:
                return {"success": False, "error": f"agent {agent_id} already exists"}
            acb = AgentControlBlock(agent_id)
            self._agents[agent_id] = acb
            logger.info("acb created: %s", agent_id)
            return {"success": True, "agent_id": agent_id, "acb": acb.to_dict()}

    def get(self, agent_id: str) -> dict:
        """Get an ACB for an agent."""
        with self._lock:
            acb = self._agents.get(agent_id)
            if not acb:
                return {"success": False, "error": f"agent {agent_id} not found"}
            return {"success": True, "agent_id": agent_id, "acb": acb.to_dict()}

    def delete(self, agent_id: str) -> dict:
        """Delete an ACB for an agent."""
        with self._lock:
            acb = self._agents.pop(agent_id, None)
            if not acb:
                return {"success": False, "error": f"agent {agent_id} not found"}
            return {"success": True, "agent_id": agent_id, "removed": True}

    def set_slot(self, agent_id: str, slot: str, value: Any, source: str = "") -> dict:
        """Set a slot value for an agent."""
        with self._lock:
            acb = self._agents.get(agent_id)
            if not acb:
                return {"success": False, "error": f"agent {agent_id} not found"}
            return acb.set(slot, value, source)

    def get_slot(self, agent_id: str, slot: str, default: Any = None) -> dict:
        """Read a slot value for an agent."""
        with self._lock:
            acb = self._agents.get(agent_id)
            if not acb:
                return {"success": False, "error": f"agent {agent_id} not found"}
            value = acb.get(slot, default)
            return {"success": True, "agent_id": agent_id, "slot": slot, "value": value}

    def list(self) -> dict:
        """List all agents."""
        with self._lock:
            agents = [{"agent_id": aid, "slots": len(acb._slots), "created_at": acb.created_at}
                      for aid, acb in self._agents.items()]
            return {"success": True, "agents": agents, "count": len(agents)}

    def snapshot(self, agent_id: str) -> dict:
        """Agent state snapshot."""
        with self._lock:
            acb = self._agents.get(agent_id)
            if not acb:
                return {"success": False, "error": "agent not found"}
            return {"success": True, "snapshot": acb.snapshot()}

    def export_all(self) -> dict:
        """Export all ACBs."""
        with self._lock:
            data = {aid: acb.to_dict() for aid, acb in self._agents.items()}
            return {"success": True, "agents": data, "count": len(data)}

    def import_all(self, data: dict) -> dict:
        """Import ACBs."""
        count = 0
        for agent_id, acb_data in data.get("agents", {}).items():
            acb = AgentControlBlock.from_dict(acb_data)
            with self._lock:
                self._agents[agent_id] = acb
            count += 1
        return {"success": True, "imported": count}


# ═════════════════════════════════════════════════════════════════════════════
# Register default slots
# ═════════════════════════════════════════════════════════════════════════════

register_slot("task_state", "IDLE", "Statecharts task region state")
register_slot("health_state", "HEALTHY", "Statecharts health region state")
register_slot("reputation", 0.85, "Agent reputation 0-1")
register_slot("priority", 3, "Scheduling priority 1-5")
register_slot("token_budget", 73000, "Token budget")
register_slot("token_consumed", 0, "Tokens consumed")
register_slot("current_card", "", "Current card ID")
register_slot("last_heartbeat", 0.0, "Last heartbeat timestamp")
register_slot("restart_count", 0, "Restart count")

# ═════════════════════════════════════════════════════════════════════════════
# Global singleton
# ═════════════════════════════════════════════════════════════════════════════

_service: ACBService | None = None


def get_service() -> ACBService:
    global _service
    if _service is None:
        _service = ACBService()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None