"""IssueCard + IssueTable tests — submit, get, status, answer, supplement."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestIssueData:
    def test_issue_status_enum(self):
        from l3.issue import IssueStatus
        assert IssueStatus.PENDING.name == "PENDING"

    def test_issue_card_status_enum(self):
        from l3.issue import IssueCardStatus
        assert IssueCardStatus.DRAFT.name == "DRAFT"


class TestIssueTable:
    def test_get_table_singleton(self):
        from l3.issue import get_table
        t1 = get_table()
        t2 = get_table()
        assert t1 is t2

    def test_submit_and_get(self):
        from l3.issue import IssueCard, IssueItem, get_table
        table = get_table()
        card = IssueCard(intent="Test", domain="r", agent_ids=["a"])
        card.items.append(IssueItem(question="Q1", domain="r"))
        card_id = table.submit(card)
        assert card_id is not None
        fetched = table.get(card_id)
        assert fetched is not None
        assert fetched.intent == "Test"

    def test_get_not_found(self):
        from l3.issue import get_table
        table = get_table()
        card = table.get("nonexistent")
        assert card is None

    def test_set_status(self):
        from l3.issue import IssueCard, IssueItem, IssueCardStatus, get_table
        table = get_table()
        card = IssueCard(intent="Status", domain="t", agent_ids=["a"])
        card_id = table.submit(card)
        table.set_status(card_id, IssueCardStatus.DELIBERATING)
        fetched = table.get(card_id)
        assert fetched.status == IssueCardStatus.DELIBERATING

    def test_answer_item(self):
        from l3.issue import IssueCard, IssueItem, get_table
        table = get_table()
        item = IssueItem(question="Q1", domain="r", assigned_to="agent-a")
        card = IssueCard(intent="Answer test", domain="t", agent_ids=["agent-a"])
        card.items.append(item)
        card_id = table.submit(card)
        ok = table.answer_item(card_id, item.id, "Answer text", "agent-a")
        assert ok

    def test_supplement(self):
        from l3.issue import IssueCard, IssueItem, get_table
        table = get_table()
        item = IssueItem(question="Q1", domain="r")
        card = IssueCard(intent="Suppl test", domain="t", agent_ids=["a"])
        card.items.append(item)
        card_id = table.submit(card)
        new_id = table.supplement(card_id, "New issue?", "routes", "agent-b")
        assert new_id is not None

    def test_list_by_status(self):
        from l3.issue import IssueCard, IssueItem, IssueCardStatus, get_table
        table = get_table()
        card = IssueCard(intent="ListByStatus", domain="t", agent_ids=["a"])
        card_id = table.submit(card)
        table.set_status(card_id, IssueCardStatus.DELIBERATING)
        cards = table.list_by_status(IssueCardStatus.DELIBERATING)
        assert any(c.get("id") == card_id for c in cards)
