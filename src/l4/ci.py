"""CI service — continuous integration pipeline management.

Runs build/test pipelines, tracks status, provides logs.
Supports local execution and GitHub Actions integration.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from l1.kernel.params.api import CI_SHELL_TIMEOUT
from l1.kernel.params.system import CI_DEFAULT_TIMEOUT, CI_DEFAULT_LIST_LIMIT, CI_DEFAULT_LOG_LINES, CI_MAX_RUNS, CI_PIPELINE_CACHE_TTL, HASH_TRUNC_SHORT, LOG_TRUNC_20, LOG_TRUNC_500
from l1.kernel.platform import SHELL_PATH
from l3._base import BaseService

logger = logging.getLogger(__name__)


class PipelineStatus:
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class PipelineRun:
    """A single CI pipeline run."""
    run_id: str
    name: str
    status: str = PipelineStatus.PENDING
    steps: list[dict] = field(default_factory=list)
    output: list[str] = field(default_factory=list)
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    elapsed: float = 0.0
    agent_id: str = ""


class CIService(BaseService):
    """CI service — manages pipeline runs."""

    def __init__(self, max_runs: int = CI_MAX_RUNS):
        super().__init__("ci")
        self._runs: dict[str, PipelineRun] = {}
        self._lock = threading.RLock()
        self._max_runs = max_runs
        self._total_runs = 0

    def _on_start(self) -> dict:
        return {"success": True, "max_runs": self._max_runs}

    def _on_stop(self) -> dict:
        with self._lock:
            self._runs.clear()
        return {"success": True}

    def run_pipeline(self, name: str, steps: list[dict],
                     agent_id: str = "", timeout: float = CI_DEFAULT_TIMEOUT) -> dict:
        """Run a CI pipeline with given steps.

        Steps format:
          [{"action": "build", "cmd": "python setup.py build"},
           {"action": "test", "cmd": "pytest tests/"},
           {"action": "lint", "cmd": "flake8 ."}]
        """
        run_id = f"ci-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}"
        run = PipelineRun(run_id=run_id, name=name, steps=steps, agent_id=agent_id)
        with self._lock:
            self._runs[run_id] = run
            self._total_runs += 1
            if len(self._runs) > self._max_runs:
                oldest = min(self._runs.keys(), key=lambda k: self._runs[k].started_at)
                self._runs.pop(oldest, None)

        run.status = PipelineStatus.RUNNING
        run.started_at = time.time()

        # Execute pipeline synchronously in the current thread.
        # A daemon thread was used here previously but was redundant because
        # run_pipeline() joins it immediately, blocking until completion.
        # Direct synchronous execution is simpler and avoids the pointless
        # thread creation overhead.
        self._execute(run_id, timeout)

        return {"success": True, "run_id": run_id, "name": name,
                "status": run.status, "step_count": len(steps)}

    def _execute(self, run_id: str, timeout: float) -> None:
        """Execute pipeline steps in sequence."""
        run = self._runs.get(run_id)
        if not run:
            return

        deadline = time.time() + timeout
        for i, step in enumerate(run.steps):
            if time.time() > deadline:
                run.status = PipelineStatus.TIMEOUT
                run.output.append(f"TIMEOUT after {timeout}s")
                break

            action = step.get("action", f"step-{i}")
            cmd = step.get("cmd", "")
            cwd = step.get("cwd", ".")

            run.output.append(f"[{i+1}/{len(run.steps)}] {action}: {cmd}")
            try:
                # Build the shell invocation explicitly so we never rely on
                # subprocess shell=True (which would re-expose us to shell
                # quoting bugs and make the call harder to audit). The CI
                # pipeline contract is that `cmd` is a single shell command
                # string, so we hand it to the configured shell verbatim via
                # `-c`/`/c` rather than letting subprocess split it.
                from l1.kernel.platform import IS_WINDOWS
                if IS_WINDOWS:
                    shell_args = [SHELL_PATH, "/c", cmd]
                else:
                    shell_args = [SHELL_PATH, "-c", cmd]
                r = subprocess.run(
                    shell_args, cwd=cwd,
                    capture_output=True, text=True, timeout=CI_SHELL_TIMEOUT,
                )
                step["exit_code"] = r.returncode
                if r.stdout:
                    run.output.extend(r.stdout.splitlines()[-LOG_TRUNC_20:])
                if r.stderr:
                    run.output.append(f"STDERR: {r.stderr[:LOG_TRUNC_500]}")
                if r.returncode != 0:
                    run.status = PipelineStatus.FAILED
                    run.error = f"Step {i+1} ({action}) failed with code {r.returncode}"
                    run.output.append(f"FAILED: {run.error}")
                    break
                run.output.append(f"PASS: {action}")
            except subprocess.TimeoutExpired:
                run.status = PipelineStatus.TIMEOUT
                run.error = f"Step {i+1} ({action}) timed out"
                run.output.append(f"TIMEOUT: {run.error}")
                break
            except FileNotFoundError:
                run.status = PipelineStatus.FAILED
                run.error = f"Step {i+1} ({action}): command not found: {cmd}"
                run.output.append(f"FAILED: {run.error}")
                break
            except Exception as e:
                run.status = PipelineStatus.FAILED
                run.error = f"Step {i+1} ({action}): {e}"
                run.output.append(f"FAILED: {run.error}")
                break
        else:
            run.status = PipelineStatus.PASSED
            run.output.append(f"ALL {len(run.steps)} STEPS PASSED")

        run.completed_at = time.time()
        run.elapsed = run.completed_at - run.started_at

    def get_status(self, run_id: str) -> dict:
        """Get pipeline run status."""
        with self._lock:
            run = self._runs.get(run_id)
        if not run:
            return {"success": False, "error": "run not found"}
        return {
            "success": True, "run_id": run_id, "name": run.name,
            "status": run.status, "elapsed": round(run.elapsed, 2),
            "step_count": len(run.steps),
            "steps": [{"action": s.get("action"), "exit_code": s.get("exit_code")}
                      for s in run.steps],
        }

    def get_logs(self, run_id: str, max_lines: int = CI_DEFAULT_LOG_LINES) -> dict:
        """Get pipeline run logs."""
        with self._lock:
            run = self._runs.get(run_id)
        if not run:
            return {"success": False, "error": "run not found"}
        return {
            "success": True, "run_id": run_id,
            "output": run.output[-max_lines:],
            "line_count": min(len(run.output), max_lines),
        }

    def list_runs(self, status: str | None = None, limit: int = CI_DEFAULT_LIST_LIMIT) -> dict:
        """List pipeline runs."""
        with self._lock:
            runs = list(self._runs.values())
        if status:
            runs = [r for r in runs if r.status == status]
        runs.sort(key=lambda r: r.started_at, reverse=True)
        return {
            "success": True,
            "runs": [{"run_id": r.run_id, "name": r.name, "status": r.status,
                      "elapsed": round(r.elapsed, 2), "steps": len(r.steps)}
                     for r in runs[:limit]],
            "count": min(len(runs), limit),
        }

    def stats(self) -> dict:
        with self._lock:
            statuses = {}
            for r in self._runs.values():
                statuses[r.status] = statuses.get(r.status, 0) + 1
            return {
                "total_runs": self._total_runs,
                "active_runs": len(self._runs),
                "by_status": statuses,
            }


_service: CIService | None = None
_service_lock = threading.Lock()


def get_service() -> CIService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = CIService()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None