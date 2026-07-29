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

    all_entries = _get_sandbox_entries(cell, target)
    for peer in peers:
        payload = {
            "file": target, "card_id": card_id, "action": action,
            "from": completed_agent,
        }
        if all_entries:
            payload["sandbox_entries"] = all_entries
            lines = [f"Please review changes to {target}:"]
            for e in all_entries:
                agent = e["agent_id"]
                tool = e.get("tool_name", action)
                stats = e["stats"]
                sem = e.get("semantic", "")
                lines.append(f"  {agent} ({tool}): +{stats['additions']}/-{stats['deletions']} "
                             f"{stats['hunks']} hunks{sem and f' [{sem}]' or ''}")
            payload["msg"] = "\n".join(lines)
        else:
            payload["msg"] = f"Please review changes to {target} made by {completed_agent}."
        cell.send_message(completed_agent, peer, MessageType.CROSS_REVIEW_REQ, payload)
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


def _get_sandbox_entries(cell, target: str) -> list[dict]:
    try:
        from l4.sandbox import get_manager as _get_sb_manager
        sb_mgr = _get_sb_manager()
        sb = sb_mgr.get_cell(cell.cell_id)
        if sb is None:
            return []
        result = []
        for entry in sb.get_entries():
            if entry.path != target:
                continue
            result.append({
                "hunks": entry.hunks,
                "stats": entry.stats,
                "agent_id": entry.agent_id,
                "tool_name": entry.tool_name,
                "task_id": entry.task_id,
                "conflict_level": entry.conflict_level,
                "original_hash": entry.original_hash,
                "modified_at": entry.modified_at,
            })
        return result
    except Exception:
        logger.debug("cross-review: sandbox entries lookup failed")
        return []
