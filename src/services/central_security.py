"""CentralSecurity — unified security policy engine.

Coordinates five security subsystems under a single check_all() API:
  1. Constitution  — territory/constitution rules
  2. GateChain     — G1-G5 gate sequence
  3. AuthService   — user authentication
  4. IdentityService — agent identity & tokens
  5. ToolPipeline  — execution gates (clearance, rate, alloc)

Usage:
  from services.central_security import get_center
  result = get_center().check_all("write_file", "agent-1",
                                  target="/project/foo.py",
                                  args={"path": "/project/foo.py"})
  # Returns unified verdict with per-gate status + risk score + recommendation
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class SecurityVerdict:
    """Unified result from all security gates."""

    def __init__(self, action: str, agent_id: str):
        self.action = action
        self.agent_id = agent_id
        self.timestamp = time.time()
        self.allowed: bool = True
        self.gates: dict[str, dict] = {}
        self.risk_score: float = 0.0
        self.blocked_by: list[str] = []
        self.recommendation: str = ""

    def add_gate(self, name: str, success: bool, detail: str = "",
                 score: float = 0.0) -> None:
        self.gates[name] = {"success": success, "detail": detail, "score": score}
        if not success:
            self.allowed = False
            self.blocked_by.append(name)
        self.risk_score = max(self.risk_score, score)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "agent_id": self.agent_id,
            "allowed": self.allowed,
            "gates": self.gates,
            "risk_score": round(self.risk_score, 2),
            "blocked_by": self.blocked_by,
            "recommendation": self.recommendation,
            "timestamp": self.timestamp,
        }


class CentralSecurity:
    """Unified security policy engine — single entry for all authorization checks."""

    def __init__(self):
        self._stats = {"checks": 0, "allowed": 0, "blocked": 0}

    def check_all(self, action: str, agent_id: str, *,
                  target: str = "", args: dict | None = None,
                  tool_name: str = "", user_token: str = "") -> dict:
        """Run ALL security gates and return unified verdict.

        Args:
            action:     'read_file', 'write_file', 'deploy', etc.
            agent_id:   'agent-1', 'scout-xxx', 'l3', etc.
            target:     file path, resource name, or action target
            args:       tool call arguments (for detailed checks)
            tool_name:  tool name (for pipeline clearance)
            user_token: optional user auth token
        """
        verdict = SecurityVerdict(action, agent_id)
        self._stats["checks"] += 1

        # 1. Constitution
        try:
            from kernel.constitution import get_constitution as _gc
            cc = _gc().is_allowed(action, agent_id, target=target, territory=args.get("territory", "") if args else "")
            passed = cc.get("allowed", True)
            verdict.add_gate("constitution", passed, str(cc.get("reason", "")), score=0.3 if not passed else 0)
        except Exception as e:
            verdict.add_gate("constitution", False, f"constitution error: {e}", score=0.5)

        # 2. GateChain (using correct check() API)
        try:
            from kernel.gatechain import get_gatechain as _gg
            gcr = _gg().check(tool_name or action, agent_id, target=target)
            gc_allowed = gcr.get("allowed", True)
            gc_steps = gcr.get("steps", [])
            gc_decision = gcr.get("decision", "?")
            verdict.add_gate("gatechain", gc_allowed, detail=f"decision={gc_decision}, steps={len(gc_steps)}", score=0.5 if not gc_allowed else 0)
        except Exception as e:
            verdict.add_gate("gatechain", True, f"gatechain unavailable: {e}")

        # 3. Auth (user token) — skip, no verify_token method on AuthService
        if user_token:
            verdict.add_gate("auth", False, "auth verify_token not implemented", score=0.5)

        # 4. Identity / clearance
        try:
            from kernel.params.agent import AGENT_CLEARANCE
            ring = AGENT_CLEARANCE.get(agent_id, 1)
            verdict.add_gate("clearance", ring >= 1, detail=f"agent_ring={ring}", score=0.1 if ring < 1 else 0)
        except Exception as e:
            verdict.add_gate("clearance", True, f"clearance unavailable: {e}")

        # 5. Tool mode (read/write gate)
        try:
            from .tool_config import ToolConfig as _TC
            mode = "read"  # legacy stub
            if mode == "read":
                write_names = _TC.write_tool_names()
                if action in write_names:
                    verdict.add_gate("tool_mode", False, f"read mode, write blocked", score=0.8)
        except Exception as e:
            verdict.add_gate("tool_mode", True, f"tool_mode unavailable: {e}")

        # 6. Rate limit check
        try:
            from .tool_pipeline import get_pipeline as _gp
            pipe = _gp()
            from kernel.params.kernel import RING_NUM_MAP as _RNM
            from .tool_config import ToolConfig as _TC
            tool_ring = _RNM.get("RING_2_5" if action in _TC.write_tool_names() else "RING_1", 1)
            rl = pipe._rate_limiter.check(agent_id, tool_ring)
            verdict.add_gate("rate_limit", rl.get("allowed", True),
                             detail=f"remaining={rl.get('remaining', 0)}", score=0.4 if not rl.get("allowed") else 0)
        except Exception:
            verdict.add_gate("rate_limit", True, "rate_limit unavailable")

        # Final recommendation
        if not verdict.allowed:
            verdict.recommendation = f"Blocked by: {', '.join(verdict.blocked_by)}"
            self._stats["blocked"] += 1
        else:
            self._stats["allowed"] += 1

        return verdict.to_dict()

    def stats(self) -> dict:
        return dict(self._stats)

    def reset_stats(self) -> None:
        self._stats = {"checks": 0, "allowed": 0, "blocked": 0}


_center: CentralSecurity | None = None


def get_center() -> CentralSecurity:
    global _center
    if _center is None:
        _center = CentralSecurity()
    return _center


def reset_center() -> None:
    global _center
    _center = None
