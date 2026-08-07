"""CardExecutionMixin — card execution paths for AgentTerminal.

Extracted from agent_terminal/__init__.py (P1-2 split).  ``CardResult`` /
``TerminalCard`` / ``CardMode`` and the pipeline/context helpers are imported
lazily from the parent module to avoid a circular import.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from l1.kernel.params.agent import R4_CARD_TAG_PREFIX
from l1.kernel.params.system import (
    HASH_TRUNC_SHORT,
    LOG_TRUNC_60,
    LOG_TRUNC_200,
    LOG_TRUNC_500,
    MEMORY_IMPORTANCE_DECISION,
    MEMORY_PROMOTION_THRESHOLD,
)

if TYPE_CHECKING:
    from l3.agent._term_types import CardResult, TerminalCard
    from l3.memory.cache import ContextRegister

logger = logging.getLogger(__name__)


class CardExecutionMixin:
    """CardExecutionMixin — single/batch card execution with context cycle."""

    # ── Attributes injected by the concrete AgentTerminal (see agent_terminal/__init__.py) ──
    agent_id: str
    cell_id: str
    context: ContextRegister
    _persistent_loop: bool
    _active_loop: Any
    _active_loop_lock: Any

    def _convention_handler(self, card: TerminalCard) -> CardResult:
        """Handle a convention card (implemented by AgentTerminal)."""
        raise NotImplementedError

    def _handle_direct(self, card: TerminalCard) -> CardResult:
        """Handle a direct message (implemented by AgentTerminal)."""
        raise NotImplementedError

    def _issue_card(self, card: TerminalCard) -> CardResult:
        """Route an issue card (implemented by AgentTerminal)."""
        raise NotImplementedError

    def _process_card(self, card: TerminalCard) -> CardResult:
        """Route a terminal card to its execution path."""
        from l3.agent_terminal import CardMode

        if card.action == "convention":
            return self._convention_handler(card)
        if card.action == "direct_message":
            return self._handle_direct(card)
        if card.mode == CardMode.ISSUE:
            return self._issue_card(card)
        # Persistent AgentLoop: reuse across cards for conversational continuity
        if self._persistent_loop and card.action == "think":
            with self._active_loop_lock:
                if self._active_loop is not None:
                    return self._execute_with_existing_loop(card)
        return self._execute_card(card)

    def _execute_with_existing_loop(self, card) -> dict:
        """Execute a card using the persistent AgentLoop, adding to existing conversation."""
        import time as _time

        from l3.agent_terminal import CardResult

        t0 = _time.time()
        task = card.params.get("prompt", card.target)
        # Card→skill linkage for persistent loops: the loop is reused across
        # cards, so re-bias its skill retrieval to the current card's
        # nature/domain before continuing.
        try:
            _ptags = []
            _nature = card.params.get("_card_nature", "") if hasattr(card, "params") else ""
            _domain = card.params.get("_card_domain", "") if hasattr(card, "params") else ""
            if _nature:
                _ptags.append(f"{R4_CARD_TAG_PREFIX}{_nature}")
            if _domain:
                _ptags.append(f"{R4_CARD_TAG_PREFIX}{_domain}")
            if _ptags and self._active_loop is not None:
                self._active_loop.update_card_context(tags=_ptags, nature=_nature)
        except Exception:
            logger.debug("agent_terminal: card context refresh failed")
        # Restore context_trail from snapshot if loop has none (e.g. after restart)
        if self._active_loop and not self._active_loop._context_trail:
            try:
                from ..agent.agent_persist import load_snapshot

                snap = load_snapshot(self.agent_id)
                if snap and "context_trail" in snap:
                    self._active_loop._context_trail = snap["context_trail"]
            except Exception:
                logger.debug("agent_terminal: snapshot context restore failed", exc_info=True)
        ar: dict = {}
        try:
            from ..agent.agent_persist import append_transcript

            ar = self._active_loop.continue_run(task=task)
        except Exception as e:
            ar = {"success": False, "error": str(e), "answer": ""}
        answer = ar.get("answer", "") or ""
        success = ar.get("success", False)
        # Inject result into Cell L2 cache
        try:
            self._inject_loop_result(card, answer, success)
        except Exception:
            logger.debug("agent_terminal: inject loop result failed")
        try:
            from l1.kernel.params.agent import LOG_TRUNC_200 as _T200

            append_transcript(
                self.agent_id,
                {
                    "task": task[:_T200],
                    "success": success,
                    "elapsed": round(_time.time() - t0, 2),
                    "summary": answer[:_T200],
                },
            )
        except Exception:
            logger.debug("agent_terminal: append transcript failed")
        return CardResult(
            card_id=card.card_id,
            action=card.action,
            success=success,
            output=answer,
            error=ar.get("error", ""),
            elapsed=round(_time.time() - t0, 3),
        )

    def _inject_loop_result(self, card, answer: str, success: bool) -> None:
        """Inject AgentLoop result into Cell L2 cache for cross-agent sharing."""
        from l3.cell import get_cell as _get_cell

        cell = _get_cell(self.cell_id)
        import hashlib as _hl

        key = f"persistent:{self.agent_id}:{_hl.sha256(answer.encode()).hexdigest()[:HASH_TRUNC_SHORT]}"
        summary = answer.strip()[:LOG_TRUNC_200]
        if success and answer:
            cell.cache.inject(
                key=key,
                value=answer,
                summary=summary,
                agent_id=self.agent_id,
                entry_type="decision",
                importance=MEMORY_PROMOTION_THRESHOLD,
            )
        elif not success:
            cell.cache.inject(
                key=key,
                value=answer,
                summary=f"FAIL [{self.agent_id}]: {summary}",
                agent_id=self.agent_id,
                entry_type="failure",
                importance=MEMORY_IMPORTANCE_DECISION,
            )

    def _execute_card(self, card) -> dict:
        """Execute a terminal card through the tool pipeline (single or batch)."""
        from l1.kernel import emit_signal
        from l1.kernel.params.agent import (
            EVENT_REVIEW_REQUESTED,
            TERMINAL_CONTEXT_RECENT,
            TERMINAL_SCOUT_FINDINGS_LIMIT,
        )
        from l3.agent._term_handlers import get_action_handler
        from l3.agent_terminal import CardResult
        from l3.memory.context import get_context as _get_context_manager
        from l3.tool_system.tool_pipeline import get_pipeline

        phases = ["start"]
        result_output = ""
        result_findings: list[dict] = []

        # Begin context cycle: load working memory into register
        ctx = _get_context_manager()
        ctx.begin(self.agent_id, task=getattr(card, "intent", "") or card.action)
        phases.append("context_begin")

        # Build toolkit args from card params
        args = dict(card.params or {})
        if card.target:
            args.setdefault("path", card.target)
            args.setdefault("target", card.target)

        # Resolve handler via registration API (func registry → method registry → legacy _HANDLER_MAP)
        def _handler_executor(tool_name: str, tool_args: dict, agent_id: str) -> dict:
            nonlocal result_output, result_findings, phases
            h = get_action_handler(self, tool_name)
            if h:
                output, findings, ok = h(self, card, phases)
                result_output = output or str(tool_args)
                result_findings = findings or []
                # Inject scout findings into context register
                if findings:
                    for f in findings[:TERMINAL_SCOUT_FINDINGS_LIMIT]:
                        ctx.push("observation", str(f)[:LOG_TRUNC_500], source="scout")
                return {"success": ok, "output": result_output, "findings": result_findings}
            phases.append(f"execute:{tool_name}")
            result_output = f"executed {tool_name} on {card.target}"
            return {"success": True, "output": result_output}

        pipeline = get_pipeline()

        # ── Batch execution: multiple tools in parallel (Agent internal parallelism) ──
        if card.batch:
            import concurrent.futures

            batch_results: list[dict] = []
            batch_errors: list[str] = []

            def _exec_one(batch_item: dict) -> dict:
                bn = batch_item.get("name", "")
                ba = dict(batch_item.get("input", {}))
                ba.setdefault("path", ba.get("path", ba.get("target", card.target or "")))
                ba.setdefault("target", ba.get("target", ba.get("path", card.target or "")))
                return pipeline.execute(tool_name=bn, agent_id=self.agent_id, args=ba, _executor=_handler_executor)

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(card.batch)) as ex:
                futures = {ex.submit(_exec_one, item): item for item in card.batch}
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        r = fut.result()
                        batch_results.append(r)
                        if not r.get("success"):
                            batch_errors.append(r.get("error", "batch item failed"))
                    except Exception as e:
                        batch_errors.append(str(e))

            phases.append(f"batch_done:{len(batch_results)}")
            success = len(batch_errors) == 0
            pr = {
                "success": success,
                "error": "; ".join(batch_errors) if batch_errors else "",
                "steps": phases,
                "batch_results": batch_results,
            }
        else:
            # ── Single tool execution (original path) ──
            pr = pipeline.execute(
                tool_name=card.action,
                agent_id=self.agent_id,
                args=args,
                _executor=_handler_executor,
            )

        steps = pr.get("steps", []) or []
        if isinstance(steps, list):
            phases.extend(x for x in steps if isinstance(x, str))
        if not pr.get("success"):
            ctx.end(success=False, summary=pr.get("error", "pipeline rejected"))
            return CardResult(
                card_id=card.card_id,
                action=card.action,
                success=False,
                error=pr.get("error", "pipeline rejected"),
                output=result_output,
                findings=result_findings,
                phase=phases,
            )
        try:
            from l3.memory.memory import get_memory

            mem = get_memory()
            mem.remember(
                agent_id=self.agent_id,
                entry_type="card_result",
                content=f"{card.action} {card.target}: {result_output[:LOG_TRUNC_200]}",
                tags=[card.action],
                ring=1,
            )
            phases.append("memory_store")

            # ── Auto-compact on high memory pressure after think actions ──
            if card.action == "think":
                p = mem.pressure(self.agent_id)
                if p["level"] == "high":
                    snapshot = list(self.context.recent(TERMINAL_CONTEXT_RECENT))
                    compact_r = mem.compact(self.agent_id)
                    for item in snapshot:
                        self.context.store(
                            key=f"restored:{item.get('key', '')}",
                            value=item.get("value", ""),
                            agent_id=self.agent_id,
                            entry_type="restored",
                        )
                    phases.append(f"compact:{compact_r.get('merged', 0)}")
                    logger.info(
                        "auto-compact for %s: merged=%d tokens=%d",
                        self.agent_id,
                        compact_r.get("merged", 0),
                        compact_r.get("saved_tokens", 0),
                    )
        except Exception:
            phases.append("memory_store:skip")
        try:
            from l1.kernel import record_audit

            record_audit(
                f"card.{card.action}",
                self.agent_id,
                success=True,
                detail=f"{card.target}:{result_output[:LOG_TRUNC_60]}",
            )
        except Exception as e:
            logger.warning("agent terminal keepalive: %s", e)

        if card.action in ("write_file",) and result_output:
            try:
                emit_signal(
                    EVENT_REVIEW_REQUESTED,
                    sender=self.agent_id,
                    target=self.cell_id or "cell",
                    data={
                        "type": "cross_review",
                        "action": card.action,
                        "target": card.target,
                        "created_by": self.agent_id,
                        "output_snippet": result_output[:LOG_TRUNC_200],
                    },
                )
                phases.append("cross_review→signal")
            except Exception:
                phases.append("cross_review:skip")

        ctx.end(success=True, summary=f"{card.action} {card.target}: {result_output[:LOG_TRUNC_200]}")
        phases.append("context_end")

        return CardResult(
            card_id=card.card_id,
            action=card.action,
            success=True,
            output=result_output,
            findings=result_findings,
            phase=phases,
        )
