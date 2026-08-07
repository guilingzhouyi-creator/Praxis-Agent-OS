"""CardConventionMixin — convention-protocol routing for CardRegistry.

Extracted from card_registry.py (P2 split).  ``CardLifecycle`` is imported
lazily from the parent module to avoid a circular import.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from l1.kernel.params.system import LOG_TRUNC_500

if TYPE_CHECKING:
    from l3.card.card_unified import CardUnified

logger = logging.getLogger(__name__)


class CardConventionMixin:
    """CardConventionMixin — route cards through the convention protocol."""

    # ── Attributes injected by the concrete CardRegistry (see card_registry.py) ──
    _lock: threading.RLock
    _cards: dict[str, CardUnified]
    _cell_map: dict[str, Any]
    _cell_resolver: Callable[[str], Any] | None

    def complete(self, card_id: str, result: dict | None = None,
                 error: str = "") -> bool:
        """Complete a card (implemented by CardRegistry)."""
        raise NotImplementedError

    def hold_card(self, card_id: str) -> None:
        """Hold a card pending convention convergence (implemented by CardRegistry)."""
        raise NotImplementedError

    def _route_to_convention(self, card_id: str, intent: str,
                             domain: str) -> None:
        """Route a card to ConventionProtocol instead of direct Cell dispatch.

        Creates an IssueCard linked to the source card, convenes the Cell's
        peer agents, and holds the source card until convergence completes
        (close_convention() completes it via source_card_id).
        """
        resolver = self._cell_resolver
        if not resolver:
            logger.warning("card %s: no cell resolver for convention", card_id)
            self.complete(card_id, error="no cell resolver for convention")
            return
        cell_id = ""
        try:
            cell_id = next(iter(self._cell_map.keys())) if self._cell_map else ""
            cell = resolver(cell_id)
        except Exception as e:
            logger.warning("card %s: convention cell resolve failed: %s", card_id, e)
            self.complete(card_id, error=f"convention cell resolve failed: {e}")
            return

        try:
            from l3.card.issue import IssueCard, get_table
            issue = IssueCard(title=intent, intent=intent, domain=domain)
            issue.agent_ids = list(cell._agents.keys())
            issue.cell_id = cell.cell_id
            issue.source_card_id = card_id
            get_table().submit(issue)

            from l3.cell.components.cell_convention import convene
            convene(cell, issue)
            with self._lock:
                rec = self._cards.get(card_id)
                if rec:
                    rec.summary.columns["_issue_card_id"] = issue.id
            self.hold_card(card_id)
            logger.info("card %s routed to convention %s (%d agents)",
                        card_id, issue.id, len(issue.agent_ids))
        except Exception as e:
            logger.warning("card %s convention start failed: %s", card_id, e)
            self.complete(card_id, error=f"convention start failed: {e}")

    def _complete_convention_card(self, issue_card_id: str,
                                  convergence_doc: str = "") -> None:
        """Complete the source card after a convention converges.

        Only a bounded summary + file/archive references are injected into
        the session — the full deliberation .md stays on disk (readable via
        l3a_convention) to avoid polluting the session context window.
        """
        from l3.card.card_registry import CardLifecycle
        try:
            from l3.card.issue import get_table
            issue = get_table().get(issue_card_id)
        except Exception:
            issue = None
        if not issue or not issue.source_card_id:
            return
        src = issue.source_card_id
        with self._lock:
            rec = self._cards.get(src)
            if not rec or rec.state == CardLifecycle.COMPLETED:
                return
        # Locate persisted doc file for the reference
        doc_path = ""
        try:
            import os as _os

            from l1.kernel.params.agent import CONVENTION_DOC_DIR
            from l1.kernel.paths import get_paths as _gp
            doc_path = _os.path.join(_gp().data_dir, CONVENTION_DOC_DIR,
                                     f"{issue_card_id}.md")
            if not _os.path.isfile(doc_path):
                doc_path = ""
        except Exception:
            doc_path = ""
        self.complete(src, result={
            "convergence": convergence_doc[:LOG_TRUNC_500],
            "issue_card_id": issue_card_id,
            "doc_path": doc_path,
            "archive_ref": f"CONVENTION:{issue_card_id}",
        })
        logger.info("card %s completed after convention %s (doc=%s)",
                    src, issue_card_id, doc_path or "n/a")
