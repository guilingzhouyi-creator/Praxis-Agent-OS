"""CiReviewService — card-triggered CI review daemon.

When an execution card completes, the service collects the card's changed
files from the sandbox (per-agent entries), runs targeted quality gates
(ruff / mypy / related pytest) over them via the L4 CIService pipeline,
produces a CardCiReport, persists it (JSONL + R4 archive), and emits
events for observability.

Optional downstream linkages (approval / convention / reputation / lean
trace / notify / todo) are config-gated and always non-blocking — a
failing consumer never blocks the report or the card lifecycle.
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import logging
import os
import queue
import re
import shlex
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.system import (
    CI_CONTROL_API_WRITABLE,
    CI_CONTROL_SHELL_WRITABLE,
    CI_DEFAULT_LIST_LIMIT,
    CI_REVIEW_ARCHIVE_FONDS,
    CI_REVIEW_ARCHIVE_SERIES,
    CI_REVIEW_DEDUP_TTL,
    CI_REVIEW_MAX_CONCURRENT,
    CI_REVIEW_MAX_FILES,
    CI_REVIEW_MYPY_CMD,
    CI_REVIEW_PERSIST_FILE,
    CI_REVIEW_PYTEST_CMD,
    CI_REVIEW_QUEUE_CAP,
    CI_REVIEW_RUFF_CMD,
    CI_REVIEW_TIMEOUT,
    LOG_TRUNC_200,
)
from l3._base import BaseService
from l3.error_bus import capture

logger = logging.getLogger(__name__)

# Functional setting suffixes (without the ci.review. prefix).  Business
# surfaces (API / L2 Shell) may mutate these globally or per scope
# (cell / agent).  Control-plane keys (ci.control.*) are writable too but
# require an explicit admin confirmation (see _is_control_key).
CI_SETTING_SUFFIXES: frozenset[str] = frozenset(
    {
        "enabled",
        "auto_trigger",
        "llm_review",
        "gates",
        "escalate_reject",
        "route_convention",
        "reputation",
        "lean_trace",
        "todo_linkage",
        "notify.enabled",
    }
)

# Back-compat alias: the full ci.review.* key set derived from suffixes.
CI_SETTING_KEYS: frozenset[str] = frozenset(f"ci.review.{s}" for s in CI_SETTING_SUFFIXES)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_control_key(key: str) -> bool:
    """True for control-plane keys (ci.control.*) — API-writable with admin."""
    return key in ("ci.control.api.writable", "ci.control.shell.writable")


def _is_allowed_key(key: str) -> bool:
    """Check a settings key against the dynamic whitelist.

    Accepts ``ci.review.<suffix>``, ``ci.review.cell.<id>.<suffix>`` and
    ``ci.review.agent.<id>.<suffix>`` (ids must match ``[A-Za-z0-9_-]+``),
    plus control-plane keys (handled separately with admin confirmation).
    """
    if _is_control_key(key):
        return True
    if not key.startswith("ci.review."):
        return False
    rest = key[len("ci.review.") :]
    parts = rest.split(".")
    if len(parts) == 1:
        return parts[0] in CI_SETTING_SUFFIXES
    if len(parts) >= 3 and parts[0] in ("cell", "agent") and ".".join(parts[2:]) in CI_SETTING_SUFFIXES:
        return bool(_ID_PATTERN.match(parts[1]))
    return False


def _normalize_key(key: str) -> str:
    """Map a short alias (e.g. ``enabled``) to its full ``ci.review.*`` key."""
    if key.startswith("ci."):
        return key
    return f"ci.review.{key}" if key in CI_SETTING_SUFFIXES else key


def _match_any(path: str, patterns: list[str]) -> bool:
    """True when *path* matches any glob pattern (case-insensitive fnmatch)."""
    lowered = path.lower()
    return any(fnmatch.fnmatch(lowered, p.lower()) for p in patterns)


@dataclass
class CardCiReport:
    """One CI review result bound to a completed card."""

    card_id: str
    run_id: str
    state: str  # completed / failed / cancelled
    verdict: str  # PASS / NEEDS_CHANGES / REJECT / SKIPPED
    agent_id: str = ""
    gates: list[dict] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    review: dict = field(default_factory=dict)
    archive_ref: str = ""
    error: str = ""
    context: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict for persistence."""
        return {
            "card_id": self.card_id,
            "run_id": self.run_id,
            "state": self.state,
            "verdict": self.verdict,
            "agent_id": self.agent_id,
            "gates": self.gates,
            "changed_files": self.changed_files,
            "review": self.review,
            "archive_ref": self.archive_ref,
            "error": self.error,
            "context": self.context,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class CiReviewService(BaseService):
    """System-hosted CI review daemon triggered by card completion."""

    def __init__(self, persist_path: str = ""):
        super().__init__("ci_review")
        self._reports: dict[str, CardCiReport] = {}
        self._dedup: dict[tuple[str, str], float] = {}
        self._queue: queue.Queue = queue.Queue(maxsize=CI_REVIEW_QUEUE_CAP)
        self._jsonl_lock = threading.Lock()
        self._registered = False
        if not persist_path:
            try:
                from l1.kernel.paths import get_paths as _gp

                persist_path = os.path.join(_gp().data_dir, CI_REVIEW_PERSIST_FILE)
            except Exception:
                persist_path = CI_REVIEW_PERSIST_FILE
        self._persist_path = persist_path
        # Bounded worker pool: CI_REVIEW_MAX_CONCURRENT daemon workers consume
        # the bounded queue — both concurrency and queued work are capped.
        # Deployment override: praxis.yaml ci.review.max_concurrent (settings).
        # Guarded coercion (P2 review fix): non-numeric settings fall back to
        # the default, and 0/negative values cannot silently disable the pool.
        try:
            _raw_mc = self._effective("max_concurrent", "", "", CI_REVIEW_MAX_CONCURRENT)
            max_concurrent = int(_raw_mc) if str(_raw_mc).strip() else CI_REVIEW_MAX_CONCURRENT
            if max_concurrent < 1:
                max_concurrent = CI_REVIEW_MAX_CONCURRENT
        except (TypeError, ValueError):
            max_concurrent = CI_REVIEW_MAX_CONCURRENT
        for _ in range(max_concurrent):
            threading.Thread(target=self._process, daemon=True, name="ci-review-worker").start()

    # ── BaseService lifecycle ──

    def _on_start(self) -> dict:
        """Mark the service ready; trigger registration happens at boot."""
        return {"success": True, "persist_path": self._persist_path}

    def _on_stop(self) -> dict:
        """Detach the completion listener and drop in-memory state."""
        with contextlib.suppress(Exception):
            self.unregister_card_trigger()
        with self._lock:
            self._reports.clear()
        return {"success": True}

    # ── Card completion trigger ──

    def register_card_trigger(self) -> dict:
        """Subscribe to card completion events (idempotent)."""
        if self._registered:
            return {"success": True, "note": "already registered"}
        try:
            from l3.card.card_registry import get_registry

            get_registry().register_completion_listener(self._on_card_completed)
            self._registered = True
            return {"success": True}
        except Exception as e:
            capture(
                "ci_review: trigger registration failed", error_code="E_CI_REVIEW_TRIGGER", component="ci_review", exc=e
            )
            self.logger.warning("ci_review: trigger registration failed: %s", e)
            return {"success": False, "error": str(e)}

    def unregister_card_trigger(self) -> dict:
        """Detach the completion listener."""
        try:
            from l3.card.card_registry import get_registry

            get_registry().unregister_completion_listener(self._on_card_completed)
        except Exception:
            pass
        self._registered = False
        return {"success": True}

    # ── Trigger handler ──

    def _on_card_completed(self, card_id: str, state: str, result: dict) -> None:
        """Completion listener — schedule a review for the card (non-blocking)."""
        agent_id = str(result.get("agent_id") or result.get("agent") or "")
        cell_id = str(result.get("cell_id") or "")
        if not bool(self._effective("enabled", agent_id, cell_id, True)):
            return
        if not bool(self._effective("auto_trigger", agent_id, cell_id, True)):
            return
        if state not in ("completed", "failed", "cancelled"):
            return
        key = (card_id, state)
        now = time.time()
        with self._lock:
            last = self._dedup.get(key)
            if last is not None and now - last < CI_REVIEW_DEDUP_TTL:
                return
            self._dedup[key] = now
            if len(self._dedup) > CI_REVIEW_QUEUE_CAP:
                oldest = min(self._dedup, key=lambda k: self._dedup[k])
                self._dedup.pop(oldest, None)
        self._submit(card_id, state, result)

    def _submit(self, card_id: str, state: str, result: dict) -> bool:
        """Enqueue a review task; False when the bounded queue is full."""
        try:
            self._queue.put_nowait((card_id, state, dict(result or {})))
            return True
        except queue.Full:
            capture(
                "ci_review: review queue full",
                error_code="E_CI_REVIEW_QUEUE_FULL",
                component="ci_review",
                task_id=card_id,
            )
            logger.warning("ci_review: queue full, dropping card %s", card_id)
            return False

    def _process(self) -> None:
        """Worker loop: pull reviews from the bounded queue (daemon)."""
        while True:
            card_id, state, result = self._queue.get()
            try:
                self._do_review(card_id, state, result)
            except Exception as e:
                capture(
                    "ci_review: review run failed",
                    error_code="E_CI_REVIEW_RUN",
                    component="ci_review",
                    exc=e,
                    task_id=card_id,
                )
                logger.warning("ci_review: review failed for card %s: %s", card_id, e)

    def _do_review(self, card_id: str, state: str, result: dict) -> None:
        """Collect changes, run gates, build and persist the report."""
        report = CardCiReport(
            card_id=card_id,
            run_id="",
            state=state,
            verdict="SKIPPED",
            agent_id=str(result.get("agent_id") or result.get("agent") or ""),
        )
        report.changed_files = self._collect_changes(card_id, result)
        cell_id = str(result.get("cell_id") or "")
        if cell_id:
            ctx = self._collect_autotest_context(cell_id)
            if ctx:
                report.context["auto_test"] = ctx
        steps = self._build_steps(report.changed_files)
        if not steps:
            report.error = "no gates applicable to changed files"
            report.completed_at = time.time()
            self._persist_report(report)
            return
        run_id, gates, error = self._run_and_wait(card_id, steps, result)
        report.run_id = run_id
        report.gates = gates
        report.error = error
        report.verdict = self._verdict(gates, error)
        if report.verdict == "PASS" and self._setting("ci.review.llm_review", False):
            report.review = self._llm_review(result)
            rv = str(report.review.get("verdict", "")).upper()
            if rv in ("NEEDS_CHANGES", "REJECT"):
                report.verdict = rv
        report.completed_at = time.time()
        self._persist_report(report)
        self._dispatch_linkages(report)

    # ── Change collection & gate building ──

    def _collect_changes(self, card_id: str, result: dict) -> list[str]:
        """Collect the card's changed files from the sandbox (per-agent entries).

        Falls back to an explicit ``changes``/``files`` list carried in the
        card result when sandbox attribution is unavailable.
        """
        files: list[str] = []
        explicit = result.get("changes") or result.get("files")
        if isinstance(explicit, list):
            files = [str(f) for f in explicit if isinstance(f, str)]
        else:
            agent_id = str(result.get("agent_id") or result.get("agent") or "")
            cell_id = str(result.get("cell_id") or "")
            if agent_id and cell_id:
                try:
                    from l4.sandbox import get_manager as _get_sb

                    sb = _get_sb().get_cell(cell_id)
                    if sb is not None:
                        files = [e.path for e in sb.get_entries(agent_id=agent_id)]
                except Exception as e:
                    capture(
                        "ci_review: sandbox lookup failed",
                        error_code="E_CI_REVIEW_SANDBOX",
                        component="ci_review",
                        exc=e,
                        task_id=card_id,
                    )
                    logger.debug("ci_review: sandbox lookup failed for card %s", card_id)
        seen: set[str] = set()
        ordered: list[str] = []
        for f in files:
            if f not in seen:
                seen.add(f)
                ordered.append(f)
            if len(ordered) >= CI_REVIEW_MAX_FILES:
                break
        return ordered

    def _collect_autotest_context(self, cell_id: str) -> dict:
        """Read the most recent AutoTestGate result from the Cell L2 cache.

        Informational only (``report.context.auto_test``) — never affects
        the verdict; full-suite regression stays owned by AutoTestGate.
        Non-blocking: cache miss, empty cell, or any error returns {}.
        """
        if not self._setting("ci.review.consume_auto_test_cache", True):
            return {}
        try:
            from l3.cell import get_cell as _get_cell

            cell = _get_cell(cell_id)
            if cell is None:
                return {}
            cache = cell.cache
            best = None
            best_ts = 0.0
            for key in cache.keys():  # noqa: SIM118 — CellCache is not iterable
                if not key.startswith("auto_test:"):
                    continue
                entry = cache.lookup(key)
                if entry is None:
                    continue
                if entry.timestamp >= best_ts:
                    best_ts = entry.timestamp
                    best = entry
            if best is None:
                return {}
            value = best.value or {}
            return {
                "passed": value.get("passed"),
                "failures": len(value.get("failures") or []),
                "at": value.get("at", 0),
                "summary": (best.summary or "")[:LOG_TRUNC_200],
            }
        except Exception as e:
            capture(
                "ci_review: autotest context failed", error_code="E_CI_REVIEW_AUTOTEST", component="ci_review", exc=e
            )
            logger.debug("ci_review: autotest context failed: %s", e)
            return {}

    def _apply_matcher(self, gate: str, files: list[str]) -> list[str]:
        """Filter changed files for a gate using ``ci.review.matchers``.

        Matcher spec per gate: ``{"include": [...], "exclude": [...]}`` —
        include empty means unrestricted; exclude wins over include.
        No matcher config (or an invalid spec) returns the files unchanged
        so behaviour stays identical to the pre-matcher versions.
        """
        matchers = self._setting("ci.review.matchers", {})
        spec = matchers.get(gate) if isinstance(matchers, dict) else None
        if not isinstance(spec, dict):
            return files
        include = spec.get("include") or []
        exclude = spec.get("exclude") or []
        if not include and not exclude:
            return files
        return [
            f
            for f in files
            if not (exclude and _match_any(f, exclude)) and not (include and not _match_any(f, include))
        ]

    def _build_steps(self, files: list[str]) -> list[dict]:
        """Build pipeline steps for the configured gates over changed files."""
        gates = self._setting("ci.review.gates", ["ruff", "mypy", "pytest"])
        if isinstance(gates, str):
            gates = [g.strip() for g in gates.split(",") if g.strip()]
        py_files = [f for f in files if f.endswith(".py")]
        steps: list[dict] = []
        ruff_files = self._apply_matcher("ruff", py_files)
        if "ruff" in gates and ruff_files:
            steps.append(
                {
                    "action": "ruff",
                    "cmd": CI_REVIEW_RUFF_CMD.format(files=" ".join(shlex.quote(f) for f in ruff_files)),
                }
            )
        mypy_files = self._apply_matcher("mypy", py_files)
        if "mypy" in gates and mypy_files:
            steps.append(
                {
                    "action": "mypy",
                    "cmd": CI_REVIEW_MYPY_CMD.format(files=" ".join(shlex.quote(f) for f in mypy_files)),
                }
            )
        if "pytest" in gates:
            tests = self._related_tests(self._apply_matcher("pytest", py_files))
            if tests:
                steps.append(
                    {
                        "action": "pytest",
                        "cmd": CI_REVIEW_PYTEST_CMD.format(files=" ".join(shlex.quote(t) for t in tests)),
                    }
                )
        return steps

    @staticmethod
    def _related_tests(py_files: list[str]) -> list[str]:
        """Find likely test modules for changed python files under tests/."""
        import glob as _glob

        found: list[str] = []
        for f in py_files:
            stem = os.path.basename(f)
            if stem.startswith("test_"):
                found.append(f)
                continue
            module = stem[:-3] if stem.endswith(".py") else stem
            found.extend(_glob.glob(f"tests/**/test_{module}.py", recursive=True))
        return sorted(set(found))

    # ── Pipeline execution ──

    def _run_and_wait(self, card_id: str, steps: list[dict], result: dict) -> tuple[str, list[dict], str]:
        """Run the gate pipeline via CIService and poll until completion.

        Returns (run_id, gates, error) so the report can link back to the
        underlying PipelineRun.
        """
        from l4.ci import get_service as _get_ci

        agent_id = str(result.get("agent_id") or result.get("agent") or "")
        # Per-card pipeline timeout; deployment override: praxis.yaml
        # ci.review.timeout (settings), default CI_REVIEW_TIMEOUT.
        # Guarded coercion (P2 review fix): non-numeric values fall back to
        # the default instead of raising inside the worker loop.
        try:
            _raw_to = self._effective("timeout", "", "", CI_REVIEW_TIMEOUT)
            timeout = int(_raw_to) if str(_raw_to).strip() else CI_REVIEW_TIMEOUT
        except (TypeError, ValueError):
            timeout = CI_REVIEW_TIMEOUT
        r = _get_ci().run_pipeline(
            name=f"card-{card_id}",
            steps=steps,
            agent_id=agent_id,
            timeout=timeout,
            card_id=card_id,
        )
        run_id = r.get("run_id", "")
        deadline = time.time() + timeout + 10
        error = ""
        while time.time() < deadline:
            time.sleep(0.5)
            st = _get_ci().get_status(run_id)
            status = st.get("status", "")
            if status in ("passed", "failed", "cancelled", "timeout"):
                gates = [
                    {
                        "action": s.get("action"),
                        "exit_code": s.get("exit_code"),
                        "status": "passed" if s.get("exit_code") == 0 else "failed",
                    }
                    for s in st.get("steps", [])
                ]
                if status != "passed":
                    error = st.get("error", status)
                break
        else:
            error = f"timed out waiting for CI pipeline ({timeout}s)"
            gates = [{"action": s.get("action"), "exit_code": None, "status": "unknown"} for s in steps]
        return run_id, gates, error

    @staticmethod
    def _verdict(gates: list[dict], error: str) -> str:
        """Derive the verdict from gate results."""
        if error:
            return "NEEDS_CHANGES"
        return "PASS" if all(g.get("exit_code") == 0 for g in gates) else "NEEDS_CHANGES"

    # ── Settings helper ──

    def _setting(self, key: str, default: Any) -> Any:
        """Read a runtime setting from SettingsCenter (best-effort)."""
        try:
            from l3.config.settings_center import get_center

            return get_center().get(key, default)
        except Exception as e:
            capture(
                "ci_review: settings read failed",
                error_code="E_CI_REVIEW_SETTING",
                component="ci_review",
                exc=e,
                context={"key": key},
            )
            return default

    def _effective(self, suffix: str, agent_id: str = "", cell_id: str = "", default: Any = None) -> Any:
        """Resolve a setting across scopes: agent > cell > global.

        Args:
            suffix: functional suffix without the ``ci.review.`` prefix
                (e.g. ``"enabled"``).
            agent_id / cell_id: optional scope selectors for the card.
            default: fallback when no scope override and no global value.

        Returns:
            The resolved value.  A scope override only applies when its key
            is present in the settings (``None`` means "not set").
        """
        if agent_id:
            v = self._setting(f"ci.review.agent.{agent_id}.{suffix}", None)
            if v is not None:
                return v
        if cell_id:
            v = self._setting(f"ci.review.cell.{cell_id}.{suffix}", None)
            if v is not None:
                return v
        return self._setting(f"ci.review.{suffix}", default)

    def _surface_writable(self, surface: str) -> bool:
        """Check whether a control surface may mutate ci.review.* settings.

        Args:
            surface: "api" or "shell" — the calling control surface.

        Returns:
            True when writes are allowed (default True; settings failure
            degrades to allowed so a broken settings path never silently
            locks the feature).
        """
        default = CI_CONTROL_API_WRITABLE if surface == "api" else CI_CONTROL_SHELL_WRITABLE
        return bool(self._setting(f"ci.control.{surface}.writable", default))

    # ── LLM review (optional) ──

    def _llm_review(self, result: dict) -> dict:
        """Run the optional LLM reviewer over the card result (non-blocking)."""
        try:
            from l3.agent.review import perform_review

            agent_id = str(result.get("agent_id") or result.get("agent") or "system")
            task = str(result.get("intent") or result.get("task") or "")
            return perform_review(agent_id=agent_id, reviewer_id="ci", task=task, result=result, llm_call=None)
        except Exception as e:
            capture("ci_review: LLM review failed", error_code="E_CI_REVIEW_LLM", component="ci_review", exc=e)
            logger.debug("ci_review: LLM review failed: %s", e)
            return {"verdict": "SKIPPED", "reason": str(e)}

    # ── Persistence & events ──

    def _persist_report(self, report: CardCiReport) -> None:
        """Persist the report: in-memory + JSONL + R4 archive + events."""
        with self._lock:
            self._reports[report.card_id] = report
        payload = json.dumps(report.to_dict(), ensure_ascii=False, default=str)
        self._append_jsonl(payload)
        try:
            from l3.tools._archive import _cmd_archive_store

            ar = _cmd_archive_store(
                fonds=CI_REVIEW_ARCHIVE_FONDS,
                series=CI_REVIEW_ARCHIVE_SERIES,
                content=payload,
                tags=f"card:{report.card_id},verdict:{report.verdict}",
            )
            report.archive_ref = str(ar.get("ref_code") or ar.get("archive_ref") or "") if isinstance(ar, dict) else ""
        except Exception as e:
            capture(
                "ci_review: R4 archive failed",
                error_code="E_CI_REVIEW_ARCHIVE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
            )
            logger.debug("ci_review: R4 archive failed: %s", e)
        self._emit_events(report)

    def _append_jsonl(self, payload: str) -> None:
        """Append one report line to the JSONL file (thread-safe)."""
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with self._jsonl_lock:
                with open(self._persist_path, "a", encoding="utf-8") as f:
                    f.write(payload + "\n")
        except Exception as e:
            capture("ci_review: JSONL persist failed", error_code="E_CI_REVIEW_PERSIST", component="ci_review", exc=e)
            logger.warning("ci_review: JSONL persist failed: %s", e)

    def _emit_events(self, report: CardCiReport) -> None:
        """Broadcast the review result on EventBus and MonitorBus."""
        try:
            from l1.kernel import get_event_bus

            if report.verdict == "PASS":
                evt = "ci.review.completed"
            elif report.verdict == "SKIPPED":
                evt = "ci.review.skipped"
            else:
                evt = "ci.review.failed"
            get_event_bus().emit_event(
                evt,
                {
                    "card_id": report.card_id,
                    "run_id": report.run_id,
                    "verdict": report.verdict,
                    "gates": report.gates,
                    "elapsed": round(report.completed_at - report.started_at, 2),
                },
                source="ci_review",
            )
        except Exception as e:
            capture("ci_review: event emit failed", error_code="E_CI_REVIEW_EVENT", component="ci_review", exc=e)
            logger.debug("ci_review: event emit failed")
        try:
            from l3.bus.monitor_bus import MonitorEvent
            from l3.bus.monitor_bus import get_bus as _get_mbus

            severity = (
                "info"
                if report.verdict in ("PASS", "SKIPPED")
                else ("warn" if report.verdict == "NEEDS_CHANGES" else "crit")
            )
            _get_mbus().emit(
                MonitorEvent(
                    type="ci.card.review",
                    source="ci_review",
                    severity=severity,
                    card_id=report.card_id,
                    data={"verdict": report.verdict, "gates": [g.get("action") for g in report.gates]},
                )
            )
        except Exception as e:
            capture("ci_review: monitor emit failed", error_code="E_CI_REVIEW_EVENT", component="ci_review", exc=e)
            logger.debug("ci_review: monitor emit failed")

    # ── Downstream linkages (config-gated, non-blocking) ──

    def _dispatch_linkages(self, report: CardCiReport) -> None:
        """Fire config-gated downstream consumers based on the verdict.

        Every consumer is wrapped in its own suppression so a failing
        linkage can never abort the remaining consumers or the report.
        """
        with contextlib.suppress(Exception):
            if report.verdict == "REJECT" and self._setting("ci.review.escalate_reject", False):
                self._link_approval(report)
        with contextlib.suppress(Exception):
            if report.verdict == "NEEDS_CHANGES" and self._setting("ci.review.route_convention", False):
                self._link_convention(report)
        with contextlib.suppress(Exception):
            if report.review and self._setting("ci.review.reputation", False):
                self._link_reputation(report)
        with contextlib.suppress(Exception):
            if report.verdict != "PASS" and self._setting("ci.review.lean_trace", False):
                self._link_lean_trace(report)
        with contextlib.suppress(Exception):
            if report.verdict in ("REJECT", "NEEDS_CHANGES") and self._setting("ci.review.notify.enabled", False):
                self._link_notify(report)
        with contextlib.suppress(Exception):
            if report.verdict != "PASS" and self._setting("ci.review.todo_linkage", False):
                self._link_todo(report)

    def _link_approval(self, report: CardCiReport) -> None:
        """Escalate a REJECT verdict to the ApprovalGate (optional)."""
        try:
            from l3.card.approval_gate import get_gate

            get_gate().request(
                "ci.review",
                report.agent_id or "system",
                {"card_id": report.card_id, "run_id": report.run_id},
                reason=f"CI review {report.verdict}: {report.error}",
            )
        except Exception as e:
            capture(
                "ci_review: approval linkage failed",
                error_code="E_CI_REVIEW_LINKAGE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
                context={"linkage": "approval"},
            )
            logger.debug("ci_review: approval linkage failed: %s", e)

    def _link_convention(self, report: CardCiReport) -> None:
        """Route a NEEDS_CHANGES verdict to cross-agent Convention (optional)."""
        try:
            from l3.card.card_registry import get_registry

            reg = get_registry()
            intent = domain = ""
            rec = reg.get(report.card_id)
            if rec is not None:
                cols = getattr(getattr(rec, "summary", None), "columns", None) or {}
                intent = cols.get("intent", "")
                domain = cols.get("domain", "")
            reg._route_to_convention(report.card_id, intent=intent, domain=domain)
        except Exception as e:
            capture(
                "ci_review: convention linkage failed",
                error_code="E_CI_REVIEW_LINKAGE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
                context={"linkage": "convention"},
            )
            logger.debug("ci_review: convention linkage failed: %s", e)

    def _link_reputation(self, report: CardCiReport) -> None:
        """Adjust the executing agent's reputation from an LLM review (optional)."""
        try:
            from l1.kernel.reputation import get_reputation

            get_reputation().record_review(report.agent_id or "system", approved=report.verdict == "PASS")
        except Exception as e:
            capture(
                "ci_review: reputation linkage failed",
                error_code="E_CI_REVIEW_LINKAGE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
                context={"linkage": "reputation"},
            )
            logger.debug("ci_review: reputation linkage failed: %s", e)

    def _link_lean_trace(self, report: CardCiReport) -> None:
        """Archive a failure trace for R4Agent skill evolution (optional)."""
        try:
            from l3.tools._archive import _cmd_archive_store

            entry = {"card_id": report.card_id, "verdict": report.verdict, "gates": report.gates, "error": report.error}
            _cmd_archive_store(
                fonds="skills",
                series="lean_trace",
                content=json.dumps(entry, ensure_ascii=False),
                tags=f"ci_review,{report.agent_id or 'system'},failure",
            )
        except Exception as e:
            capture(
                "ci_review: lean trace failed",
                error_code="E_CI_REVIEW_LINKAGE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
                context={"linkage": "lean_trace"},
            )
            logger.debug("ci_review: lean trace failed: %s", e)

    def _link_notify(self, report: CardCiReport) -> None:
        """Push a notification for a failing verdict (optional).

        Webhook mode: when ``ci.review.notify.webhook_url`` is configured
        and the verdict's event is in ``ci.review.notify.webhook_events``
        (default failed/rejected), POSTs a structured payload through the
        notify webhook channel.  Otherwise falls back to the configured
        notify channel (log|email|slack|sms).
        """
        try:
            from l4.notify import get_service as _get_notify

            channel = str(self._setting("ci.review.notify.channel", "log"))
            message = f"CI review {report.verdict} for card {report.card_id}"
            webhook_url = str(self._setting("ci.review.notify.webhook_url", "") or "")
            events = self._setting("ci.review.notify.webhook_events", ["failed", "rejected"]) or []
            if webhook_url and self._verdict_event(report.verdict) in events:
                payload = json.dumps(
                    {
                        "card_id": report.card_id,
                        "verdict": report.verdict,
                        "gates": report.gates,
                        "error": report.error,
                        "agent_id": report.agent_id,
                        "timestamp": report.completed_at or report.started_at,
                    },
                    ensure_ascii=False,
                )
                _get_notify().send(channel="webhook", to=webhook_url, subject=message, body=payload)
                return
            _get_notify().send(
                channel=channel, to=report.agent_id or "system", subject="Praxis notification", body=message
            )
        except Exception as e:
            capture(
                "ci_review: notify linkage failed",
                error_code="E_CI_REVIEW_LINKAGE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
                context={"linkage": "notify"},
            )
            logger.debug("ci_review: notify linkage failed: %s", e)

    @staticmethod
    def _verdict_event(verdict: str) -> str:
        """Map a verdict to a webhook event name."""
        return {
            "PASS": "passed",
            "NEEDS_CHANGES": "failed",
            "REJECT": "rejected",
            "SKIPPED": "skipped",
        }.get(verdict, "failed")

    def _link_todo(self, report: CardCiReport) -> None:
        """Record a fix-up task for a failing verdict (optional)."""
        try:
            from l3.services.todo_tracker import TodoTracker

            content = f"ci-review:{report.card_id} ({report.verdict})"
            tracker = TodoTracker()
            tracker.update(content, "add")
            tracker.update(content, "escalated")
        except Exception as e:
            capture(
                "ci_review: todo linkage failed",
                error_code="E_CI_REVIEW_LINKAGE",
                component="ci_review",
                exc=e,
                task_id=report.card_id,
                context={"linkage": "todo"},
            )
            logger.debug("ci_review: todo linkage failed: %s", e)

    # ── Query & stats ──

    def rerun(self, card_id: str) -> dict:
        """Manually re-run the review for a card using its latest report.

        Explicit user action — bypasses the dedup window.  The run executes
        in a background daemon thread under the concurrency cap and reuses
        the previous report's changed files / agent, so a review can be
        re-executed after a fix or a config change without a new card.
        """
        with self._lock:
            prev = self._reports.get(card_id)
        if prev is None:
            return {"success": False, "error": f"no CI review history for card: {card_id}"}
        result = {"agent_id": prev.agent_id or "", "changes": list(prev.changed_files)}
        self._submit(card_id, prev.state or "completed", result)
        return {"success": True, "card_id": card_id, "queued": True}

    def query(self, card_id: str = "", status: str = "", limit: int = CI_DEFAULT_LIST_LIMIT) -> dict:
        """Query review reports (in-memory)."""
        with self._lock:
            reports = list(self._reports.values())
        if card_id:
            reports = [r for r in reports if r.card_id == card_id]
        if status:
            reports = [r for r in reports if r.verdict == status]
        reports.sort(key=lambda r: r.completed_at, reverse=True)
        return {"success": True, "reports": [r.to_dict() for r in reports[:limit]], "count": min(len(reports), limit)}

    def stats(self) -> dict:
        """Aggregate review stats by verdict."""
        with self._lock:
            by_verdict: dict[str, int] = {}
            for r in self._reports.values():
                by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1
            return {"total": len(self._reports), "by_verdict": by_verdict}


_service: CiReviewService | None = None
_service_lock = threading.Lock()


def get_service() -> CiReviewService:
    """Get the CiReviewService singleton."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = CiReviewService()
    return _service


def reset_service() -> None:
    """Reset the singleton (for testing / hot-reload)."""
    global _service
    if _service is not None:
        with contextlib.suppress(Exception):
            _service.unregister_card_trigger()
        _service.stop()
    _service = None
