"""ConventionProtocol — deliberation protocol for Peer Agents.

Full-group discussion flow:
  1. Broadcast issue card → all Peer Agents
  2. Each Agent answers issues according to territory
  3. Agents propose supplementary issues
  4. Sequential cross-examination: Agent A → B → C → ... → A (CONVENTION_MAX_ROUNDS rounds)
  5. Convergence summary → CacheDocument → Archive → L3A converts to execution card

Message types (cell_types.py):
  CONVENE        — Convene the convention
  CROSS_EXAMINE  — Cross-examine a specific Agent
  REBUT          — Rebuttal
  PROPOSE_ISSUE  — Propose a new issue
  CONVENE_CLOSE  — Close the convention
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from l1.kernel import EVENT_TASK_ASSIGN, emit_signal
from l1.kernel.params.agent import CONVENTION_MAX_ROUNDS, CONVENTION_TIMEOUT
from l3.cell_types import CellProtocol, MessageType
from l3.issue import IssueCard, IssueCardStatus, IssueStatus, get_table

logger = logging.getLogger(__name__)


@dataclass
class ConventionTranscript:
    """Transcript entry — one statement in a round."""
    speaker: str = ""
    target: str = ""       # Agent being cross-examined
    statement: str = ""
    msg_type: str = ""     # "cross_examine" | "rebut" | "propose"
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConventionRound:
    """One round of cross-examination."""
    round_num: int = 0
    speaker_order: list[str] = field(default_factory=list)
    current_index: int = 0
    transcripts: list[ConventionTranscript] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)


class ConventionProtocol:
    """Convention protocol engine.

    Manages:
      - Participant list (agent_ids)
      - Speaking order
      - Cross-examination rounds
      - Issue table reference
      - Document cache reference
    """

    def __init__(self, issue_card: IssueCard, cell: CellProtocol):
        self.issue_card = issue_card
        self.cell = cell
        self.agent_ids: list[str] = list(issue_card.agent_ids)
        self._rounds: list[ConventionRound] = []
        self._current_round: ConventionRound | None = None
        self._lock = threading.Lock()
        self._started_at = 0.0
        self._completed_at = 0.0
        self._cache_ref = ""       # CacheDocument buffer_id
        self._archive_ref = ""     # Archive entry_id
        self._table = get_table()

    # ── Public API ──

    def start(self) -> dict:
        """Phase 1: Broadcast issue card → start convention."""
        card = self.issue_card
        self._table.set_status(card.id, IssueCardStatus.DELIBERATING)
        self._started_at = time.time()

        # Broadcast CONVENE to all participating Agents
        for aid in self.agent_ids:
            self._send_message(aid, MessageType.CONVENE, {
                "card_id": card.id, "title": card.title,
                "intent": card.intent, "domain": card.domain,
                "items": [it.to_dict() for it in card.items],
                "agent_ids": self.agent_ids,
            })

        self._current_round = ConventionRound(round_num=1)
        self._rounds.append(self._current_round)
        emit_signal(EVENT_TASK_ASSIGN, sender="convention", target="cell",
                     data={"card_id": card.id, "event": "convene"})
        logger.info("convention started: %s — %d agents, %d items",
                    card.id, len(self.agent_ids), len(card.items))
        return {"success": True, "card_id": card.id, "agents": self.agent_ids}

    def answer(self, agent_id: str, item_id: str, answer: str) -> dict:
        """Phase 2: Agents answer issues by territory."""
        card = self.issue_card
        ok = self._table.answer_item(card.id, item_id, answer, agent_id)
        if not ok:
            return {"success": False, "error": f"item {item_id} not assigned to {agent_id}"}
        self._add_transcript(agent_id, "", "rebut", f"answers {item_id}: {answer[:200]}")
        return {"success": True}

    def propose(self, agent_id: str, question: str, domain: str = "") -> dict:
        """Phase 3: Agents propose supplementary issues."""
        card = self.issue_card
        iid = self._table.supplement(card.id, question, domain, agent_id)
        if not iid:
            return {"success": False, "error": "card not found"}
        self._add_transcript(agent_id, "", "propose", f"proposes new issue: {question[:200]}")
        emit_signal(EVENT_TASK_ASSIGN, sender=agent_id, target="cell",
                     data={"card_id": card.id, "event": "propose_issue", "item_id": iid})
        return {"success": True, "item_id": iid}

    def cross_examine(self, speaker: str, target: str, statement: str) -> dict:
        """Phase 4: Cross-examine a specific agent."""
        if target not in self.agent_ids:
            return {"success": False, "error": f"unknown target: {target}"}
        self._add_transcript(speaker, target, "cross_examine", statement)
        self._send_message(target, MessageType.CROSS_EXAMINE, {
            "card_id": self.issue_card.id,
            "from": speaker, "statement": statement,
        })
        return {"success": True}

    def rebut(self, agent_id: str, statement: str) -> dict:
        """Agent rebuttal."""
        self._add_transcript(agent_id, "", "rebut", statement)
        return {"success": True}

    def next_speaker(self) -> str | None:
        """Advance to next speaker.Returns agent_id or None (round over)."""
        with self._lock:
            r = self._current_round
            if r is None:
                return None
            r.current_index += 1
            if r.current_index >= len(r.speaker_order):
                return None
            return r.speaker_order[r.current_index]

    def advance_round(self) -> bool:
        """Enter next round. Returns False when all rounds exhausted."""
        with self._lock:
            current_num = self._current_round.round_num if self._current_round else 0
            if current_num >= CONVENTION_MAX_ROUNDS:
                return False
            self._current_round = ConventionRound(
                round_num=current_num + 1,
                speaker_order=list(self.agent_ids),
            )
            self._rounds.append(self._current_round)
            return True

    def close(self) -> dict:
        """Phase 5: Close convention → Save to CacheDocument → archive."""
        card = self.issue_card
        doc = self._build_document()

        # Save to CacheDocument
        from .cache_doc import get_store
        store = get_store()
        cache_id = store.put(
            title=f"Convention: {card.title}",
            content=doc,
            tags=["convention", card.id, card.domain],
        )
        self._cache_ref = cache_id

        # Archive to Ring 4
        try:
            from tools._archive import archive_store
            arch = archive_store(
                fonds=f"CONVENTION:{card.id}",
                series="deliberation",
                title=card.title,
                content=doc,
                tags=["convention", card.domain] + self.agent_ids,
                agent_id="system",
            )
            if arch.get("success"):
                self._archive_ref = arch["data"]["entry_id"]
                card.archive_ref = self._archive_ref
        except Exception as e:
            logger.warning("convention archive failed: %s", e)

        card.cache_ref = self._cache_ref
        self._completed_at = time.time()
        self._table.set_status(card.id, IssueCardStatus.CONVERGED)

        emit_signal(EVENT_TASK_ASSIGN, sender="convention", target="l3",
                     data={"card_id": card.id, "event": "converged",
                           "cache_ref": self._cache_ref,
                           "archive_ref": self._archive_ref})
        logger.info("convention closed: %s — %d rounds, %d transcripts",
                    card.id, len(self._rounds), self._total_transcripts())
        return {
            "success": True, "card_id": card.id,
            "cache_ref": self._cache_ref,
            "archive_ref": self._archive_ref,
            "rounds": len(self._rounds),
            "transcripts": self._total_transcripts(),
        }

    def get_document(self) -> str:
        """Get discussion doc (prefer CacheDocument cache)."""
        if self._cache_ref:
            from .cache_doc import get_store
            doc = get_store().get_content(self._cache_ref)
            if doc:
                return doc
        return self._build_document()

    def status(self) -> dict:
        return {
            "card_id": self.issue_card.id,
            "status": self.issue_card.status.name,
            "agents": self.agent_ids,
            "rounds": len(self._rounds),
            "items": len(self.issue_card.items),
            "resolved": self.issue_card.all_resolved(),
            "cache_ref": self._cache_ref,
            "archive_ref": self._archive_ref,
        }

    # ── Internal ──

    def _add_transcript(self, speaker: str, target: str,
                        msg_type: str, statement: str) -> None:
        with self._lock:
            if self._current_round:
                self._current_round.transcripts.append(ConventionTranscript(
                    speaker=speaker, target=target,
                    statement=statement, msg_type=msg_type,
                ))

    def _send_message(self, target: str, msg_type: MessageType,
                      payload: dict) -> None:
        try:
            self.cell.send_message("convention", target, msg_type, payload)
        except Exception as e:
            logger.warning("convention send to %s failed: %s", target, e)

    def _build_document(self) -> str:
        card = self.issue_card
        lines = [f"# Convention: {card.title}",
                 f"Domain: {card.domain}",
                 f"Agents: {', '.join(self.agent_ids)}",
                 f"Duration: {self._completed_at - self._started_at:.1f}s"
                     if self._completed_at else "", ""]

        lines.append("## Issues")
        for it in card.items:
            status = "[x]" if it.status == IssueStatus.RESOLVED else "[ ]"
            lines.append(f"\n### {status} {it.question} [{it.domain}]")
            lines.append(f"  Proposed by: {it.proposed_by}")
            lines.append(f"  Assigned to: {it.assigned_to}")
            if it.answer:
                lines.append(f"  Answer: {it.answer}")

        lines.append("\n## Transcripts")
        for r in self._rounds:
            lines.append(f"\n### Round {r.round_num}")
            for t in r.transcripts:
                target_str = f" → {t.target}" if t.target else ""
                lines.append(f"  [{t.msg_type}] {t.speaker}{target_str}: {t.statement[:200]}")

        return "\n".join(lines)

    def _total_transcripts(self) -> int:
        return sum(len(r.transcripts) for r in self._rounds)
