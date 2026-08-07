"""SubAgent — lightweight inline quick-check agent.

Unlike Scouts (pool-managed, async, multi-turn investigation):
  - SubAgent is synchronous: caller blocks until result
  - SubAgent is Ring 1 only (read-only tools)
  - SubAgent has no long-term memory, no session
  - Used by Peer Agents for fast inline checks (e.g., "read this file", "grep for pattern")

Design:
  Peer Agent → commission SubAgent → block → result → discard
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from l1.kernel.params.agent import SUBAGENT_LOOP_STEPS, SUBAGENT_LOOP_TIMEOUT
from l1.kernel.params.kernel import RUN_SUBPROCESS_TIMEOUT
from l1.kernel.params.system import LOG_TRUNC_100, LOG_TRUNC_300, LOG_TRUNC_500, LOG_TRUNC_4000
from l1.kernel.platform import grep_cmd as _grep_cmd
from l3.services.model_service import get_service as _get_model_service

_MODEL_SPEC = "subagent"

logger = logging.getLogger(__name__)


@dataclass
class SubAgentResult:
    """SubAgentResult — sub agent result record (task, findings, error, elapsed, success)."""
    task: str = ""
    findings: list[dict] = field(default_factory=list)
    error: str = ""
    elapsed: float = 0.0
    success: bool = False


class SubAgent:
    """Synchronous lightweight agent for fast read-only checks."""

    def __init__(self, caller_id: str):
        self.caller_id = caller_id
        self._started_at: float = 0.0

    def run(self, task: str, tools: list[str] | None = None) -> SubAgentResult:
        """Execute a quick check synchronously using Ring 1 tools only."""
        self._started_at = time.time()
        result = SubAgentResult(task=task)

        try:
            findings = self._execute(task, tools or ["read_file", "grep_search", "list_dir"])
            result.findings = findings
            result.success = True
        except Exception as e:
            result.error = str(e)
            result.success = False

        result.elapsed = round(time.time() - self._started_at, 3)
        return result

    def _execute(self, task: str, tools: list[str]) -> list[dict]:
        """Run the task through AgentLoop with Ring 1 tools only."""
        from .agent_loop import AgentLoop

        loop = AgentLoop(task=task, agent_id=self.caller_id, prompt_key="subagent.system")
        findings: list[dict] = []

        import os as _os

        def _read(args: dict, agent: str = "") -> dict:
            path = args.get("path", "")
            if not path:
                return {"success": False, "error": "path required"}
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                return {"success": True, "data": content[:LOG_TRUNC_4000], "size": len(content)}
            except Exception as e:
                return {"success": False, "error": str(e)}

        def _grep(args: dict, agent: str = "") -> dict:
            import subprocess as _sp
            pattern = args.get("pattern", "")
            path = args.get("path", ".")
            try:
                cmd = _grep_cmd(pattern, path, max_count=20)
                r = _sp.run(cmd, capture_output=True, text=True, timeout=RUN_SUBPROCESS_TIMEOUT)
                out = (r.stdout or "")[:LOG_TRUNC_4000]
                return {"success": True, "data": out} if out else {"success": True, "data": "no matches"}
            except FileNotFoundError:
                return {"success": False, "error": "grep tool not found"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        def _list(args: dict, agent: str = "") -> dict:
            path = args.get("path", ".")
            try:
                entries = _os.listdir(path)
                return {"success": True, "data": entries[:LOG_TRUNC_100], "count": len(entries)}
            except Exception as e:
                return {"success": False, "error": str(e)}

        loop.add_tool("read_file", "Read file contents", {"path": "string"}, _read)
        loop.add_tool("grep_search", "Search for pattern in files", {"pattern": "string", "path": "string"}, _grep)
        loop.add_tool("list_dir", "List directory contents", {"path": "string"}, _list)

        r = loop.run(max_steps=SUBAGENT_LOOP_STEPS, timeout=SUBAGENT_LOOP_TIMEOUT,
                      **_get_model_service().resolve_dict(_MODEL_SPEC))
        answer = r.get("answer", "")
        if answer:
            findings.append({"type": "conclusion", "content": answer[:LOG_TRUNC_500]})
        for step in r.get("steps", []):
            action = step.get("action", "")
            if action.startswith("tool:"):
                findings.append({
                    "type": action,
                    "args": step.get("args", {}),
                    "result": str(step.get("result", ""))[:LOG_TRUNC_300],
                })
        return findings


def commission(caller_id: str, task: str) -> SubAgentResult:
    """Convenience: create and run a SubAgent in one call."""
    agent = SubAgent(caller_id)
    return agent.run(task)
