"""CellCardMixin — card dispatch, execution, review, and tool injection.

Delegates card lifecycle work to the components/ helper modules
(cell_execute, cell_decompose, cell_cross_review, cell_rollback) and keeps
the thin Cell façade for the dispatch entry points. Composed by Cell.
"""

from __future__ import annotations

import json as _json
import logging
from typing import TYPE_CHECKING, Any

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.params.agent import CARD_WAIT_TIMEOUT, CELL_L3_SENDER
from l1.kernel.params.system import CROSS_REVIEW_TIMEOUT, LOG_TRUNC_80, LOG_TRUNC_5000
from l3.agent_terminal import CardMode as TermCardMode
from l3.agent_terminal import TerminalCard, TerminalStatus, get_terminal, get_terminals
from l3.cell.components.cell_cross_review import auto_cross_review as _auto_cross_review
from l3.cell.components.cell_decompose import auto_agent_map as _auto_agent_map
from l3.cell.components.cell_decompose import decompose_card as _decompose_card
from l3.cell.components.cell_execute import _cleanup_snapshot as _cs
from l3.cell.components.cell_execute import _execute_decomposed, _raw_to_card
from l3.cell.components.cell_execute import _snapshot_and_inject as _ssi
from l3.cell.components.cell_execute import _take_snapshot as _ts
from l3.cell.components.cell_execute import execute_card as _execute_card
from l3.cell.components.cell_rollback import rollback_card as _rollback_card

if TYPE_CHECKING:
    from l3.card.card_unified import CardUnified as Card

logger = logging.getLogger(__name__)


class CellCardMixin:
    """Card dispatch/execution lifecycle delegated to components/ helpers."""

    # ══ Card Dispatch ══

    def dispatch_card(
        self,
        target_agent: str,
        action: str,
        target: str = "",
        params: dict | None = None,
        mode: TermCardMode = TermCardMode.EXECUTE,
        sender: str = CELL_L3_SENDER,
    ) -> dict:
        """Dispatch a card to the appropriate agent."""
        term = get_terminal(target_agent)
        if term.status in (TerminalStatus.BOOTING, TerminalStatus.STOPPED):
            term.boot()
        if term.status == TerminalStatus.CRASHED:
            return {"success": False, "error": f"terminal {target_agent} crashed"}
        card = TerminalCard(
            mode=mode,
            action=action,
            target=target,
            params=params or {},
            sender=sender,
        )
        card_id = term.dispatch(card)
        self._pmu.increment("cards.dispatched")
        emit_signal(
            EVENT_TASK_ASSIGN,
            sender=sender,
            target=target_agent,
            data={"card_id": card_id, "action": action, "mode": mode.name},
        )

        # ══ Blocking cross-review gate for write operations ══
        try:
            from l3.tool_system.tool_config import ToolConfig

            _is_write = action in ToolConfig.write_tool_names()
        except Exception:
            _is_write = False
        if _is_write:
            review = self._auto_cross_review(target_agent, action, target, card_id)
            if not review.get("approved"):
                from l2.i18n import t as _t

                return {
                    "success": False,
                    "card_id": card_id,
                    "error": _t("core.cross_review_rejected", reason=review.get("reason", "")),
                    "review": review,
                }

        return {"success": True, "card_id": card_id}

    def convene(self, issue_card: Any, agent_map: dict[str, str] | None = None) -> dict:
        """Convene a multi-agent discussion on a topic."""
        from l3.cell.components.cell_convention import convene as _convene

        return _convene(self, issue_card)

    # ── Card conversion helpers (delegated to cell_execute.py) ──

    def _raw_to_card(self, raw_intent: str, domain: str, skip_htn: bool = False) -> Card:
        """Convert raw intent string to a structured Card. Delegates to cell_execute.py."""
        return _raw_to_card(self, raw_intent, domain, skip_htn=skip_htn)

    def _execute_decomposed(self, slices: list[dict]) -> dict:
        """Execute decomposed card slices. Delegates to cell_execute.py."""
        return _execute_decomposed(self, slices)

    def _snapshot_and_inject(self, card_id: str, card: Card) -> None:
        """Snapshot files and inject rollback context. Delegates to cell_execute.py."""
        _ssi(self, card_id, card)

    @staticmethod
    def _take_snapshot(cell: Any, path: str) -> str | None:
        """Snapshot a file by copying to temp dir (delegates to cell_execute.py)."""
        return _ts(cell, path)

    @staticmethod
    def _cleanup_snapshot(cell: Any, files: dict) -> None:
        """Clean up temporary snapshot files (delegates to cell_execute.py)."""
        _cs(cell, files)

    @staticmethod
    def _archive_item(kind: str, item: Any) -> None:
        """Archive an evicted ring buffer item to R4 Archive.

        Called by CircularBuffer.on_evict when the ring is full.
        Prevents data loss: evicted items go to permanent cold storage.
        """
        try:
            from tools._archive import archive_store

            content = _json.dumps(item, default=str, ensure_ascii=False) if not isinstance(item, str) else item
            title = item.get("intent", str(item)[:LOG_TRUNC_80]) if isinstance(item, dict) else str(item)[:LOG_TRUNC_80]
            card_id = item.get("card_id", "evicted") if isinstance(item, dict) else "evicted"
            archive_store(
                fonds=f"CELL:RING:{kind}",
                series=f"evicted:{kind}",
                title=title,
                content=content[:LOG_TRUNC_5000],
                tags=["ring_eviction", kind, card_id],
                agent_id="system",
            )
        except Exception as e:
            logging.getLogger(__name__).warning("archive_item %s: %s", kind, e)

    def rollback_card(self, card_id: str = "") -> dict:
        """Rollback changes from a card execution. Delegates to cell_rollback.py."""
        self._pmu.increment("cards.rolled_back")
        return _rollback_card(self, card_id=card_id)

    # ══ Card decomposition engine (delegates to cell_decompose.py) ══

    def decompose_card(self, card: Card, domain: str = "") -> list[dict]:
        """Decompose a card into executable steps."""
        return _decompose_card(domain, card, self.cell_id, ensure_terminal_fn=self._ensure_terminal)

    # ── Cross-review dispatch (delegates to cell_cross_review.py) ──

    def _auto_cross_review(
        self, completed_agent: str, action: str, target: str, card_id: str, timeout: float = CROSS_REVIEW_TIMEOUT
    ) -> dict:
        """After a write/delete/rename, BLOCKING wait for peer agent review.
        Delegates to cell_cross_review.py.
        """
        return _auto_cross_review(self, completed_agent, action, target, card_id, timeout=timeout)

    def execute_card(
        self, card: Any, agent_map: dict[str, str] | None = None, domain: str = "", user_id: str = ""
    ) -> dict:
        """Execute a Card through the Cell. Delegates to cell_execute.py."""
        return _execute_card(self, card, agent_map=agent_map, domain=domain, user_id=user_id)

    def _auto_agent_map(self, card: Card) -> dict[str, str]:
        return _auto_agent_map(
            card, self.cell_id, ensure_terminal_fn=lambda a, r, t: self._ensure_terminal(a, r, t or self.territory)
        )

    def _ensure_terminal(self, aid: str, role: str, territory: list[str]) -> None:
        term = get_terminal(aid, role=role, territory=territory, cell_id=self.cell_id)
        if term.status in (TerminalStatus.BOOTING, TerminalStatus.STOPPED):
            term.boot()
        if term._tool_registry is None:
            self._inject_tools(term)

    def _inject_tools(self, term: Any) -> None:
        try:
            from l3.tool_system.tool_spec import TOOL_REGISTRY

            term.set_tool_registry(TOOL_REGISTRY)
        except Exception as e:
            logger.warning("tool inject failed: %s", e)
        # Wire PMU to the global pipeline for tool execution counters
        try:
            from l3.tool_system.tool_pipeline import get_pipeline

            get_pipeline().set_pmu(self._pmu)
        except Exception as e:
            logger.warning("pipeline pmu wire failed: %s", e)
        # Wire PMU to the AgentTerminal (→ AgentLoop for compression telemetry)
        try:
            term.set_pmu(self._pmu)
        except Exception as e:
            logger.warning("term pmu wire failed: %s", e)

    def agent_tools(self, agent_id: str) -> list[dict]:
        """List tools available to a specific agent."""
        all_terms = get_terminals()
        term = all_terms.get(agent_id)
        if not term:
            return []
        return term.list_tools()

    def cell_tools(self) -> dict[str, list[dict]]:
        """List tools registered at the Cell level."""
        all_terms = get_terminals()
        result: dict[str, list[dict]] = {}
        for aid, term in all_terms.items():
            tools = term.list_tools()
            if tools:
                result[aid] = tools
        return result

    def wait_for_card(self, card_id: str, timeout: float = CARD_WAIT_TIMEOUT) -> dict | None:
        """Block until a card is dispatched."""
        for term in get_terminals().values():
            result = term.wait_for_result(card_id, timeout)
            if result:
                return {
                    "success": result.success,
                    "card_id": result.card_id,
                    "action": result.action,
                    "output": result.output,
                    "findings": result.findings,
                    "error": result.error,
                    "elapsed": result.elapsed,
                    "phases": result.phase,
                }
        return None
