"""IssueCard + IssueTable — issue card and issue table.

L3A produces an IssueCard containing multiple issues. After dispatch to Cell,
each Peer Agent responds by territory, supplements issues, and participates in cross-examination.

Flow:
  L3A → IssueCard (DRAFT)
      → DELIBERATING (broadcast to Cell, Peer Agents begin discussion)
      → CONVERGED (converged after cross-examination)
      → ARCHIVED (discussion result archived)
      → EXECUTING (L3A converts to execution card)
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from l1.kernel.paths import get_paths as _gp
from l1.kernel.params.system import HASH_TRUNC_SHORT, ISSUE_TABLE_AUTO_SAVE, LOG_TRUNC_120, LOG_TRUNC_500, LOG_TRUNC_80
from l3._persistable import PersistableMixin

logger = logging.getLogger(__name__)


class IssueStatus(Enum):
    PENDING = auto()
    ANSWERED = auto()
    SUPPLEMENTED = auto()
    RESOLVED = auto()
    WITHDRAWN = auto()


class IssueCardStatus(Enum):
    DRAFT = auto()
    DELIBERATING = auto()
    CONVERGED = auto()
    ARCHIVED = auto()
    EXECUTING = auto()


@dataclass
class IssueItem:
    """Single issue - proposed by one agent, answered by another."""

    id: str = ""
    question: str = ""
    domain: str = ""
    proposed_by: str = ""       # Proposer agent_id
    assigned_to: str = ""       # Answerer agent_id (territory matching)
    answer: str = ""
    status: IssueStatus = IssueStatus.PENDING
    created_at: float = field(default_factory=time.time)
    answered_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize this issue item to a dictionary representation."""
        return {
            "id": self.id, "question": self.question[:LOG_TRUNC_120],
            "domain": self.domain, "proposed_by": self.proposed_by,
            "assigned_to": self.assigned_to, "status": self.status.name,
            "answer": self.answer[:LOG_TRUNC_500] if self.answer else "",
            "answered_at": self.answered_at,
        }


@dataclass
class IssueCard:
    """Issue card - discussion agenda produced by L3A."""

    id: str = field(default_factory=lambda: f"issue-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}")
    title: str = ""
    intent: str = ""
    domain: str = ""
    items: list[IssueItem] = field(default_factory=list)
    status: IssueCardStatus = IssueCardStatus.DRAFT
    agent_ids: list[str] = field(default_factory=list)
    cell_id: str = ""
    created_at: float = field(default_factory=time.time)
    converged_at: float = 0.0
    archive_ref: str = ""
    cache_ref: str = ""
    metadata: dict = field(default_factory=dict)
    source_card_id: str = ""
    """CardRegistry card that routed to this convention (assembly conference mode)."""

    def add_item(self, question: str, domain: str = "",
                 proposed_by: str = "",
                 assigned_to: str = "") -> str:
        """Add a new issue item to the card and return its id."""
        item = IssueItem(
            id=f"{self.id}-{uuid.uuid4().hex[:6]}",
            question=question, domain=domain or self.domain,
            proposed_by=proposed_by, assigned_to=assigned_to,
        )
        self.items.append(item)
        return item.id

    def all_resolved(self) -> bool:
        """Return True if every item in the card is resolved."""
        return all(it.status == IssueStatus.RESOLVED for it in self.items)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this issue card to a dictionary representation."""
        return {
            "id": self.id, "title": self.title[:LOG_TRUNC_80],
            "intent": self.intent[:LOG_TRUNC_120], "domain": self.domain,
            "status": self.status.name,
            "items": [it.to_dict() for it in self.items],
            "agent_ids": self.agent_ids,
            "cell_id": self.cell_id,
            "converged_at": self.converged_at,
            "archive_ref": self.archive_ref,
            "cache_ref": self.cache_ref,
        }


class IssueTable(PersistableMixin):
    """Central issue registry. L3A, Cell, Peer Agents all operate on this table."""

    persistence_kind = "issue_table"

    def __init__(self, persist_path: str = ""):
        self._cards: dict[str, IssueCard] = {}
        self._lock = threading.RLock()
        self._init_persistence(persist_path or _gp().issue_table, ISSUE_TABLE_AUTO_SAVE)
        self._restore()
        if ISSUE_TABLE_AUTO_SAVE > 0:
            self._start_auto_save()

    def _serialize(self) -> dict:
        return {"cards": {cid: c.to_dict() for cid, c in self._cards.items()}}

    def _deserialize(self, data: dict) -> bool:
        self._cards.clear()
        for cid, d in data.get("cards", {}).items():
            card = IssueCard(
                id=d.get("id", cid), title=d.get("title", ""),
                intent=d.get("intent", ""), domain=d.get("domain", ""),
                status=IssueCardStatus[d["status"]] if "status" in d else IssueCardStatus.DRAFT,
                agent_ids=d.get("agent_ids", []),
                cell_id=d.get("cell_id", ""),
                created_at=d.get("created_at", 0.0),
                converged_at=d.get("converged_at", 0.0),
                archive_ref=d.get("archive_ref", ""),
                cache_ref=d.get("cache_ref", ""),
            )
            for item_data in d.get("items", []):
                card.add_item(
                    question=item_data.get("question", ""),
                    domain=item_data.get("domain", ""),
                    proposed_by=item_data.get("proposed_by", ""),
                    assigned_to=item_data.get("assigned_to", ""),
                )
                if item_data.get("answer"):
                    for it in card.items:
                        if it.question == item_data["question"]:
                            it.answer = item_data["answer"]
                            it.status = IssueStatus[item_data["status"]] if "status" in item_data else IssueStatus.PENDING
                            it.answered_at = item_data.get("answered_at", 0.0)
                            break
            self._cards[cid] = card
        return True

    def submit(self, card: IssueCard) -> str:
        """Register a new issue card in the table and return its id."""
        with self._lock:
            self._cards[card.id] = card
        return card.id

    def get(self, card_id: str) -> IssueCard | None:
        """Return the issue card with the given id, or None if absent."""
        with self._lock:
            return self._cards.get(card_id)

    def set_status(self, card_id: str, status: IssueCardStatus) -> bool:
        """Transition a card to the given status; stamp converged_at on CONVERGED."""
        with self._lock:
            card = self._cards.get(card_id)
            if not card:
                return False
            card.status = status
            if status == IssueCardStatus.CONVERGED:
                card.converged_at = time.time()
            return True

    def answer_item(self, card_id: str, item_id: str,
                    answer: str, agent_id: str) -> bool:
        """Record an agent's answer to an assigned issue item."""
        with self._lock:
            card = self._cards.get(card_id)
            if not card:
                return False
            for it in card.items:
                if it.id == item_id and it.assigned_to == agent_id:
                    it.answer = answer
                    it.status = IssueStatus.ANSWERED
                    it.answered_at = time.time()
                    return True
            return False

    def supplement(self, card_id: str, question: str, domain: str,
                   proposed_by: str) -> str | None:
        """Add a supplementary issue item to a card and return its id."""
        with self._lock:
            card = self._cards.get(card_id)
            if not card:
                return None
            iid = card.add_item(question, domain, proposed_by, "")
            for it in card.items:
                if it.id == iid:
                    it.status = IssueStatus.SUPPLEMENTED
                    break
            return iid

    def resolve_item(self, card_id: str, item_id: str) -> bool:
        """Mark a specific issue item as resolved."""
        with self._lock:
            card = self._cards.get(card_id)
            if not card:
                return False
            for it in card.items:
                if it.id == item_id:
                    it.status = IssueStatus.RESOLVED
                    return True
            return False

    def assign_item(self, card_id: str, item_id: str,
                    agent_id: str) -> bool:
        """Assign an issue item to a specific agent for answering."""
        with self._lock:
            card = self._cards.get(card_id)
            if not card:
                return False
            for it in card.items:
                if it.id == item_id:
                    it.assigned_to = agent_id
                    return True
            return False

    def list_by_status(self, status: IssueCardStatus | None = None) -> list[dict]:
        """List cards as dicts, optionally filtered by card status."""
        with self._lock:
            return [c.to_dict() for c in self._cards.values()
                    if status is None or c.status == status]

    def list_items_by_agent(self, agent_id: str) -> list[dict]:
        """List all issue items assigned to a given agent, annotated with card id."""
        with self._lock:
            result = []
            for card in self._cards.values():
                for it in card.items:
                    if it.assigned_to == agent_id:
                        result.append({**it.to_dict(), "card_id": card.id})
            return result

    def summary(self) -> dict:
        """Return aggregate counts of cards, items, and resolved items."""
        with self._lock:
            statuses = {}
            for c in self._cards.values():
                statuses[c.status.name] = statuses.get(c.status.name, 0) + 1
            total_items = sum(len(c.items) for c in self._cards.values())
            resolved = sum(
                1 for c in self._cards.values()
                for it in c.items if it.status == IssueStatus.RESOLVED
            )
            return {
                "cards": len(self._cards),
                "total_items": total_items,
                "resolved": resolved,
                "by_card_status": statuses,
            }


_table: IssueTable | None = None


def get_table() -> IssueTable:
    """Return the singleton IssueTable, creating it on first access."""
    global _table
    if _table is None:
        _table = IssueTable()
    return _table


def reset_table() -> None:
    """Stop auto-save, clear the singleton table and remove its persist file."""
    global _table
    if _table is not None:
        _table._stop_auto_save()
        pp = _table._persist_path
        _table._cards.clear()
        _table = None
        if pp and os.path.exists(pp):
            try:
                os.remove(pp)
            except Exception:
                logger.debug("issue: draft delete failed")
