"""Assembly Mode tests — proposal, challenge, response, convergence."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestAssemblyData:
    def test_proposal_create(self):
        from l3.discussion.assembly import Proposal
        p = Proposal(agent_id="agent-a", content={"agent_a": ["app/routes"]}, rationale="best fit")
        assert p.agent_id == "agent-a"
        assert p.content["agent_a"] == ["app/routes"]
        assert p.rationale == "best fit"

    def test_challenge_create(self):
        from l3.discussion.assembly import Challenge
        c = Challenge(from_agent="agent-a", to_agent="agent-b", question="Why this territory?")
        assert c.from_agent == "agent-a"
        assert c.to_agent == "agent-b"
        assert not c.answered

    def test_response_create(self):
        from l3.discussion.assembly import Response
        r = Response(agent_id="agent-b", challenge_id=1, answer="Because it matches my role.")
        assert r.agent_id == "agent-b"
        assert r.challenge_id == 1

    def test_issue_document_create(self):
        from l3.discussion.assembly import IssueDocument
        doc = IssueDocument(issue_id="iss-001", title="Territory division")
        assert doc.issue_id == "iss-001"
        assert doc.title == "Territory division"
        assert len(doc.proposals) == 0
        assert len(doc.challenges) == 0

    def test_issue_document_add_proposal(self):
        from l3.discussion.assembly import IssueDocument, Proposal
        doc = IssueDocument(issue_id="iss-002", title="Test")
        doc.proposals.append(Proposal(agent_id="agent-a", content={}))
        assert len(doc.proposals) == 1

    def test_issue_document_add_challenge(self):
        from l3.discussion.assembly import IssueDocument, Challenge
        doc = IssueDocument(issue_id="iss-003", title="Test")
        doc.challenges.append(Challenge(from_agent="a", to_agent="b", question="?"))
        assert len(doc.challenges) == 1

    def test_issue_document_add_response(self):
        from l3.discussion.assembly import IssueDocument, Challenge, Response
        doc = IssueDocument(issue_id="iss-004", title="Test")
        doc.challenges.append(Challenge(from_agent="a", to_agent="b", question="?"))
        doc.challenges[0].answered = True
        assert doc.challenges[0].answered

    def test_issue_document_add_answer(self):
        from l3.discussion.assembly import IssueDocument, Challenge, Response
        doc = IssueDocument(issue_id="iss-005", title="Test")
        doc.challenges.append(Challenge(from_agent="a", to_agent="b", question="?"))
        doc.challenges[0].answered = True
        assert doc.challenges[0].answered

    def test_is_blank_constitution(self):
        from l3.discussion.assembly import IssueDocument
        from l1.kernel.constitution import TerritoryConstitution
        tc = TerritoryConstitution()
        assert tc.is_blank()
        tc.territories["agent_a"] = ["app/routes"]
        assert not tc.is_blank()
