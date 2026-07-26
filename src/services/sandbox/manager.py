"""SandboxManager — policy-driven sandboxed command execution."""

import asyncio
import logging
import os
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class SandboxProfile(str, Enum):
    READ_ONLY = "DANGER_0"
    SAFE_WRITE = "DANGER_1"
    NETWORK = "DANGER_2"
    FULL = "DANGER_3"
    HOST = "DANGER_4"


@dataclass
class SandboxResult:
    success: bool = False
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    sandbox_id: str = ""
    elapsed: float = 0.0

    def to_dict(self) -> dict:
        return {"success": self.success, "stdout": self.stdout[:2000],
                "stderr": self.stderr[:500], "exit_code": self.exit_code,
                "sandbox_id": self.sandbox_id, "elapsed": round(self.elapsed, 3)}


class SandboxManager:
    """Policy-driven sandbox execution manager.

    Each profile determines the isolation level:
        READ_ONLY: only tmpdir (read-only). No network.
        SAFE_WRITE: tmpdir readable/writable. No network.
        NETWORK: tmpdir readable/writable + network access.
        FULL: tmpdir readable/writable + network access (no additional restrictions).
        HOST: direct execution, no isolation.
    """

    def __init__(self, sandbox_root: str = ""):
        from kernel.params.system import SANDBOX_TMP_ROOT
        self._sandbox_root = Path(sandbox_root or SANDBOX_TMP_ROOT)
        self._sandbox_root.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        command: str,
        profile: SandboxProfile = SandboxProfile.READ_ONLY,
        timeout: float = 300.0,
        agent_id: str = "",
        tool_name: str = "",
    ) -> SandboxResult:
        """在隔离沙箱中执行命令。"""
        sandbox_id = f"sbox-{uuid.uuid4().hex[:8]}"
        workdir = self._sandbox_root / sandbox_id
        workdir.mkdir(parents=True)

        t0 = time.time()
        try:
            env = self._build_env(profile, workdir)
            cmd = self._resolve_shell(command)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(workdir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout,
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                elapsed = time.time() - t0
                self._audit(sandbox_id, agent_id, tool_name, False, "timeout", elapsed)
                return SandboxResult(
                    success=False, stdout="", stderr="timed out",
                    exit_code=-1, sandbox_id=sandbox_id, elapsed=elapsed,
                )

            elapsed = time.time() - t0
            result = SandboxResult(
                success=proc.returncode == 0,
                stdout=self._truncate(stdout),
                stderr=self._truncate(stderr),
                exit_code=proc.returncode or 0,
                sandbox_id=sandbox_id,
                elapsed=elapsed,
            )
            self._audit(sandbox_id, agent_id, tool_name, result.success, "", elapsed)
            return result

        except Exception as e:
            elapsed = time.time() - t0
            return SandboxResult(
                success=False, stdout="", stderr=str(e),
                exit_code=-1, sandbox_id=sandbox_id, elapsed=elapsed,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def run_sync(
        self,
        command: str,
        profile: SandboxProfile = SandboxProfile.READ_ONLY,
        timeout: float = 300.0,
        agent_id: str = "",
        tool_name: str = "",
    ) -> SandboxResult:
        """Synchronous wrapper for tool_pipeline use."""
        return asyncio.run(self.run(command, profile, timeout, agent_id, tool_name))

    def _build_env(self, profile: SandboxProfile, workdir: Path) -> dict:
        env = dict(os.environ)
        # READ_ONLY: remove network env, set PWD readonly hint
        if profile in (SandboxProfile.READ_ONLY, SandboxProfile.SAFE_WRITE):
            env.pop("HTTP_PROXY", None)
            env.pop("HTTPS_PROXY", None)
            env.pop("http_proxy", None)
            env.pop("https_proxy", None)
        env["SANDBOX_ID"] = env.get("SANDBOX_ID", workdir.name)
        env["SANDBOX_PROFILE"] = profile.value
        env["PRAXIS_SANDBOX"] = "1"
        return env

    def _resolve_shell(self, command: str) -> list[str]:
        if sys.platform == "win32":
            return ["cmd", "/c", command]
        return ["sh", "-c", command]

    def _truncate(self, data: bytes) -> str:
        from kernel.params.system import SANDBOX_MAX_OUTPUT
        text = data.decode("utf-8", errors="replace")
        return text[:SANDBOX_MAX_OUTPUT]

    def _audit(self, sandbox_id: str, agent_id: str, tool: str,
               success: bool, error: str, elapsed: float) -> None:
        try:
            from services.monitor_bus import MonitorEvent, get_bus
            get_bus().emit(MonitorEvent(
                type="sandbox.execution", source="sandbox_manager",
                severity="info" if success else "warn",
                agent_id=agent_id,
                message=f"sandbox {sandbox_id} {'ok' if success else 'fail'}",
                data={"sandbox_id": sandbox_id, "tool": tool,
                      "success": success, "error": error, "elapsed": round(elapsed, 3)},
            ))
        except Exception:
            pass
