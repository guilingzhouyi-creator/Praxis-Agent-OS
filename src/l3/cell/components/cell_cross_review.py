"""Cross-review — extracted from cell/__init__.py for modularity.

Contains Cell._auto_cross_review() logic:
after write/delete, blocks and waits for peer agent review.
"""

from __future__ import annotations

import logging

from l1.kernel.params.tool import TOOL_AGENT_COORD_TIMEOUT
from l3.cell.components.cell_types import MessageType, is_peer

logger = logging.getLogger(__name__)


def auto_cross_review(cell, completed_agent: str, action: str,
                      target: str, card_id: str,
                      timeout: float = TOOL_AGENT_COORD_TIMEOUT) -> dict:
    """After a write/delete/rename, BLOCKING wait for peer agent review.

    Sends CROSS_REVIEW_REQ to all peer agents, then blocks until
    all peers respond (CROSS_REVIEW_RESP) or timeout.
    """
    from threading import Event as _Event
    if action not in ("write_file", "replace_string", "delete", "rename"):
        return {"approved": True, "action": "skip"}
    if not target:
        return {"approved": True, "action": "skip"}
    if not is_peer(completed_agent):
        return {"approved": True, "action": "skip"}

    with cell._lock:
        peers = [aid for aid in cell._agents
                 if aid != completed_agent and is_peer(aid)]
    if not peers:
        return {"approved": True, "action": "no_peers"}

    resp_events: dict[str, _Event] = {p: _Event() for p in peers}
    resp_results: dict[str, dict] = {}

    def _on_resp(sender: str, payload: dict) -> None:
        if sender in resp_events:
            resp_results[sender] = payload
            resp_events[sender].set()

    try:
        from l1.kernel.event import get_bus as _get_bus
        bus = _get_bus()
        bus.on_any(lambda sig: (
            _on_resp(sig.sender, sig.data) if (
                hasattr(sig, 'data') and
                isinstance(sig.data, dict) and
                sig.data.get("msg_type") == "CROSS_REVIEW_RESP" and
                sig.data.get("card_id") == card_id
            ) else None
        ))
    except Exception as e:
        logger.warning("cross-review subscription failed: %s", e)

    for peer in peers:
        cell.send_message(completed_agent, peer, MessageType.CROSS_REVIEW_REQ, {
            "file": target, "card_id": card_id, "action": action,
            "from": completed_agent,
            "msg": f"Please review changes to {target} made by {completed_agent}.",
        })
        logger.info("cross-review: %s -> %s for %s (blocking)", completed_agent, peer, target)

    approved = True
    reasons = []
    for peer, evt in resp_events.items():
        ok = evt.wait(timeout=timeout)
        if ok:
            resp = resp_results.get(peer, {})
            verdict = resp.get("verdict", resp.get("status", "APPROVED"))
            if verdict in ("REJECT", "REJECTED", "NEEDS_CHANGES"):
                approved = False
                reasons.append(f"{peer}: {resp.get('reason', verdict)}")
        else:
            reasons.append(f"{peer}: timeout after {timeout}s")

    return {
        "approved": approved,
        "reviews": list(resp_results.values()),
        "reason": "; ".join(reasons) if reasons else "",
    }
