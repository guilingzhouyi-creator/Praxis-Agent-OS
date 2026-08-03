"""Assembly Mode — multi-agent issue discussion for Cell.

Flow:
  L3A detects blank constitution → enters Assembly Mode
  → Issues issue card to Cell
  → Each Agent proposes territory division
  → Cross-examination: Agents challenge each other's proposals
  → Answers: Agents respond to challenges
  → Convergence: L3A collects all proposals, finds consensus
  → Constitution updated

Data structures:
  IssueDocument — single source of truth for the discussion
  Proposal — each agent's proposal
  Challenge — cross-examination question
  Response — answer to a challenge
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from l1.kernel.constitution import (
    load_territory,
    merge_proposal,
    save_territory,
)
from l1.kernel.params.system import HASH_TRUNC_SHORT, LOG_TRUNC_50

logger = logging.getLogger(__name__)


@dataclass
class Proposal:
    agent_id: str
    content: dict  # e.g. {"agent_a": ["app/routes", ...], ...}
    rationale: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class Challenge:
    from_agent: str
    to_agent: str
    question: str
    created_at: float = field(default_factory=time.time)
    answered: bool = False


@dataclass
class Response:
    agent_id: str
    challenge_id: int
    answer: str
    created_at: float = field(default_factory=time.time)


@dataclass
class IssueDocument:
    """Single source of truth for an Assembly Mode discussion."""
    issue_id: str
    title: str
    status: str = "open"  # open | converging | resolved | rejected
    proposals: list[Proposal] = field(default_factory=list)
    challenges: list[Challenge] = field(default_factory=list)
    responses: list[Response] = field(default_factory=list)
    converged: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    resolved_at: float = 0.0


class AssemblyMode:
    """Assembly Mode — multi-agent issue discussion.

    Usage:
        am = AssemblyMode()
        am.start_issue("Determine territory division")
        am.submit_proposal("agent_a", {"agent_a": ["app/routes"], "agent_b": ["app/services"]}, "by function")
        am.submit_proposal("agent_b", {"agent_a": ["app/frontend"], "agent_b": ["app/backend"]}, "by layer")
        am.challenge("agent_b", "agent_a", "Why routes?")
        am.respond("agent_a", 0, "Because routes are the entry point")
        am.converge()  → returns consensus
    """

    def __init__(self):
        self._issues: dict[str, IssueDocument] = {}
        self._current_issue_id: str = ""

    def start_issue(self, title: str) -> dict:
        """Start a new issue discussion."""
        issue_id = f"issue-{uuid.uuid4().hex[:HASH_TRUNC_SHORT]}"
        doc = IssueDocument(issue_id=issue_id, title=title)
        self._issues[issue_id] = doc
        self._current_issue_id = issue_id
        logger.info("assembly: issue started — %s (%s)", title, issue_id)
        return {"success": True, "issue_id": issue_id, "title": title}

    def submit_proposal(self, agent_id: str, content: dict, rationale: str = "") -> dict:
        """Agent submits a proposal."""
        if not self._current_issue_id:
            return {"success": False, "error": "no active issue"}
        doc = self._issues[self._current_issue_id]
        proposal = Proposal(agent_id=agent_id, content=content, rationale=rationale)
        doc.proposals.append(proposal)
        logger.info("assembly: proposal from %s — %s", agent_id, list(content.keys()))
        return {"success": True, "proposal_id": len(doc.proposals) - 1, "agent_id": agent_id}

    def challenge(self, from_agent: str, to_agent: str, question: str) -> dict:
        """Agent A challenges Agent B's proposal."""
        if not self._current_issue_id:
            return {"success": False, "error": "no active issue"}
        doc = self._issues[self._current_issue_id]
        c = Challenge(from_agent=from_agent, to_agent=to_agent, question=question)
        doc.challenges.append(c)
        logger.info("assembly: %s challenges %s — %s", from_agent, to_agent, question[:LOG_TRUNC_50])
        return {"success": True, "challenge_id": len(doc.challenges) - 1}

    def respond(self, agent_id: str, challenge_id: int, answer: str) -> dict:
        """Agent responds to a challenge."""
        if not self._current_issue_id:
            return {"success": False, "error": "no active issue"}
        doc = self._issues[self._current_issue_id]
        if challenge_id >= len(doc.challenges):
            return {"success": False, "error": "challenge not found"}
        doc.challenges[challenge_id].answered = True
        r = Response(agent_id=agent_id, challenge_id=challenge_id, answer=answer)
        doc.responses.append(r)
        logger.info("assembly: %s responds to #%d — %s", agent_id, challenge_id, answer[:LOG_TRUNC_50])
        return {"success": True}

    def converge(self) -> dict:
        """Converge all proposals into a consensus constitution.

        Strategy: majority vote on each territory assignment.
        If no consensus, return the most-supported proposal.
        """
        if not self._current_issue_id:
            return {"success": False, "error": "no active issue"}
        doc = self._issues[self._current_issue_id]
        if not doc.proposals:
            return {"success": False, "error": "no proposals to converge"}

        # Collect all mentioned agents
        all_agents = set()
        for p in doc.proposals:
            all_agents.update(p.content.keys())

        # For each agent, find the most commonly proposed territory
        consensus = {}
        for agent_id in all_agents:
            territory_votes: dict[str, int] = {}
            for p in doc.proposals:
                territories = p.content.get(agent_id, [])
                key = tuple(sorted(territories))
                territory_votes[key] = territory_votes.get(key, 0) + 1
            if territory_votes:
                best = max(territory_votes, key=territory_votes.get)
                consensus[agent_id] = list(best)

        doc.converged = consensus
        doc.status = "resolved"
        doc.resolved_at = time.time()

        # Update constitution
        c = load_territory()
        merge_proposal(c, consensus)
        save_territory(c)

        logger.info("assembly: converged — %d agents, %d territories",
                     len(consensus), sum(len(v) for v in consensus.values()))
        return {
            "success": True,
            "consensus": consensus,
            "agent_count": len(consensus),
            "territory_count": sum(len(v) for v in consensus.values()),
            "issue_id": doc.issue_id,
        }

    def status(self, issue_id: str = "") -> dict:
        """Get the current status of an issue discussion."""
        if issue_id:
            doc = self._issues.get(issue_id)
            if not doc:
                return {"success": False, "error": "issue not found"}
        elif self._current_issue_id:
            doc = self._issues[self._current_issue_id]
        else:
            return {"success": False, "error": "no active issue"}

        return {
            "success": True,
            "issue_id": doc.issue_id,
            "title": doc.title,
            "status": doc.status,
            "proposals": len(doc.proposals),
            "challenges": len(doc.challenges),
            "responses": len(doc.responses),
            "converged": bool(doc.converged),
        }


_assembly: AssemblyMode | None = None


def get_assembly() -> AssemblyMode:
    global _assembly
    if _assembly is None:
        _assembly = AssemblyMode()
    return _assembly


def reset_assembly() -> None:
    global _assembly
    _assembly = None
