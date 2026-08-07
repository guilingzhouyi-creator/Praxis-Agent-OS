"""Tests for Convention — multi-agent discussion lifecycle, message routing."""

from __future__ import annotations

from l3.card.issue import IssueCard, get_table
from l3.cell import get_cell, reset_cells
from l3.cell.components.cell_types import MessageType


def _make_issue_card(title: str = "test issue") -> IssueCard:
    card = IssueCard(
        id=f"issue-{id(title)}",
        title=title,
        intent="Discuss territory assignment",
        domain="cluster",
        cell_id="cell-1",
    )
    get_table().submit(card)
    return card


def test_convene():
    cell = get_cell("cell-1")
    cell.add_agent("agent-a", role="reader", territory=["src"])
    cell.add_agent("agent-b", role="writer", territory=["doc"])
    card = _make_issue_card()
    try:
        r = cell.convene(card)
        assert r.get("success"), f"convene failed: {r}"
        assert "convention" in r
        assert r["convention"].get("success")
    finally:
        reset_cells()


def test_convene_blank_constitution():
    cell = get_cell("cell-2")
    cell.add_agent("agent-x", role="default", territory=["."])
    card = _make_issue_card("blank territory")
    try:
        r = cell.convene(card)
        assert r.get("success"), f"blank convene failed: {r}"
    finally:
        reset_cells()


def test_send_convention_message():
    cell = get_cell("cell-3")
    cell.add_agent("agent-a", role="reader", territory=["src"])
    card = _make_issue_card("messaging")
    try:
        r = cell.convene(card)
        assert r.get("success")
        conv_id = r["convention"]["card_id"]
        msg_r = cell.send_message(
            "agent-a", "agent-a", MessageType.CONVENE, payload={"session_id": conv_id, "card_id": card.id}
        )
        assert msg_r.get("success"), f"send_message failed: {msg_r}"
    finally:
        reset_cells()


def test_close_convention():
    cell = get_cell("cell-4")
    cell.add_agent("agent-a", role="default", territory=["."])
    card = _make_issue_card("close test")
    try:
        r = cell.convene(card)
        assert r.get("success")
        conv_id = r["convention"]["card_id"]
        close_r = cell.close_convention(conv_id)
        assert close_r.get("success"), f"close failed: {close_r}"
    finally:
        reset_cells()
