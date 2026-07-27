"""SupplementManager — extract, classify, and route supplementary issues.

After cross-Cell answer aggregation, supplements are extracted and
classified into:
  - cross_cell:   requires coordination with other Cells
  - within_cell:  can be resolved within the originating Cell
  - human_only:   requires human decision

cross_cell supplements are routed back to IssueTable for rebroadcast.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SupplementManager:
    """Classify and route supplementary issues."""

    def classify(self, supplements: list[dict]) -> dict:
        """Classify supplements by scope.

        Each supplement dict: {title, description, source_cell, source_agent}
        """
        cross_cell: list[dict] = []
        within_cell: list[dict] = []
        human_only: list[dict] = []

        for supp in supplements:
            scope = self._determine_scope(supp)
            if scope == "cross_cell":
                cross_cell.append(supp)
            elif scope == "within_cell":
                within_cell.append(supp)
            else:
                human_only.append(supp)

        return {
            "total": len(supplements),
            "cross_cell": cross_cell,
            "within_cell": within_cell,
            "human_only": human_only,
        }

    def cross_cell_route(self, supplement: dict, session_id: str) -> dict:
        """Route a cross-cell supplement to IssueTable for rebroadcast.

        Creates a new IssueItem in the existing IssueCard, then emits
        a bus event for Cell rebroadcast.
        """
        try:
            from l3.card.issue import get_table
            table = get_table()

            # Find the IssueCard for this session
            # (session_id is stored in metadata when issue was created)
            issue_card = self._find_issue_card(table, session_id)
            if issue_card:
                table.supplement(
                    issue_card.id,
                    session_id=session_id,
                    question=supplement.get("description", supplement.get("title", "")),
                    domain=supplement.get("domain", "cross-cell"),
                )
                logger.info("supplement routed: %s → %s",
                            supplement.get("title", "?")[:40], issue_card.id)
        except Exception as e:
            logger.warning("supplement route: %s", e)

        return {"success": True, "title": supplement.get("title", "")}

    def batch_route(self, supplements: list[dict], session_id: str) -> dict:
        """Route multiple cross-cell supplements."""
        results = []
        for supp in supplements:
            r = self.cross_cell_route(supp, session_id)
            results.append(r)
        return {"success": True, "routed": len(results)}

    def _determine_scope(self, supplement: dict) -> str:
        """Heuristic scope determination based on content.
        
        cross_cell: mentions other cells, coordination, territory
        human_only: mentions approval, decision, policy, security
        within_cell: everything else
        """
        desc = (supplement.get("description", "") + " " +
                supplement.get("title", "")).lower()
        human_keywords = ["approval", "policy", "decision", "security",
                         "permission", "compliance", "audit"]
        cross_keywords = ["cell", "coordination", "territory", "shared",
                         "cross-cell", "broadcast", "all cells"]

        if any(kw in desc for kw in human_keywords):
            return "human_only"
        if any(kw in desc for kw in cross_keywords):
            return "cross_cell"
        return "within_cell"

    def _find_issue_card(self, table: Any, session_id: str) -> Any:
        """Find the IssueCard associated with a session."""
        try:
            cards = table.list_by_status("DELIBERATING")
            for c in cards:
                if hasattr(c, "metadata") and c.metadata:
                    if c.metadata.get("session_id") == session_id:
                        return c
        except Exception:
            pass
        return None
