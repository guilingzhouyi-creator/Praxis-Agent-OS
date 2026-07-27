"""VerifyCadence — edit-then-verify nudging with subprocess checks for AgentLoop.

Agent-harness-style: after edits, runs deterministic verification commands
via subprocess and records evidence. Close gate blocks unverified edits.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class VerifyCadence:
    """Edit-then-verify with subprocess checks."""
    from l1.kernel.params.system import VERIFY_CMDS as VERIFY_CMDS

    def __init__(self):
        self._edited: set[str] = set()
        self._nudged: set[str] = set()
        self._evidence: list[dict] = []
        self._enabled = self._read_enabled()

    @staticmethod
    def _read_enabled() -> bool:
        try:
            from l3.settings_center import get_center
            return bool(get_center().get("loop.verify_cadence", True))
        except Exception:
            return True

    def record_edit(self, path: str) -> None:
        if path:
            self._edited.add(path)

    def record_check(self, command: str) -> None:
        if self._is_verifying(command):
            self._edited.clear()

    def nudge(self) -> str | None:
        if not self._enabled:
            return None
        unverified = [p for p in self._edited if p not in self._nudged]
        if not unverified:
            return None
        self._nudged.update(unverified)
        paths = "\n".join(f"  - {p}" for p in unverified[:3])
        return (
            f"Unverified edits detected:\n{paths}\n\n"
            f"Run a fast check: execute a verification command and use "
            f"'todowrite' with status='verified' when checks pass."
        )

    def run_check(self, command: str, cwd: str = "",
                  timeout: int = 120) -> dict:
        """Run a verification check via subprocess. Returns result with evidence."""
        import subprocess as _sp
        try:
            r = _sp.run(command, shell=True, capture_output=True, text=True,
                        timeout=timeout, cwd=cwd or None)
            passed = r.returncode == 0
            evidence = f"exit {r.returncode}"
            if passed:
                evidence += f" | stdout: {r.stdout[:200].strip()}" if r.stdout.strip() else ""
            else:
                evidence += f" | stderr: {r.stderr[:200].strip()}" if r.stderr.strip() else ""
            entry = {"command": command, "exit_code": r.returncode,
                     "passed": passed, "evidence": evidence}
            self._evidence.append(entry)
            return {"success": passed, "exit_code": r.returncode,
                    "evidence": evidence, "stdout": r.stdout[:500], "stderr": r.stderr[:500]}
        except _sp.TimeoutExpired:
            entry = {"command": command, "exit_code": -1, "passed": False,
                     "evidence": f"timeout ({timeout}s)"}
            self._evidence.append(entry)
            return {"success": False, "exit_code": -1, "evidence": f"timeout ({timeout}s)"}
        except Exception as e:
            entry = {"command": command, "exit_code": -1, "passed": False,
                     "evidence": str(e)}
            self._evidence.append(entry)
            return {"success": False, "exit_code": -1, "evidence": str(e)}

    def can_close(self) -> tuple[bool, list[str]]:
        unverified = [p for p in self._edited if p not in self._nudged]
        return len(unverified) == 0, list(unverified)

    def evidence_log(self) -> list[dict]:
        return list(self._evidence)

    def reset(self) -> None:
        self._edited.clear()
        self._nudged.clear()
        self._evidence.clear()

    @staticmethod
    def _is_verifying(command: str) -> bool:
        cmd = command.strip().split()[0] if command else ""
        return cmd in VerifyCadence.VERIFY_CMDS
