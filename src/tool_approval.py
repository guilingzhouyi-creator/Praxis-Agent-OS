"""Ring 3 approval/witness — IPC cross-review + human approval flow.

Depends: services/ipc.py (message bus), constants.py (WitnessStatus)
"""

from __future__ import annotations

from typing import Any

from l1.kernel.params.gatechain import WitnessStatus
from l3.bus.ipc import IPCMessage, MessageType, get_bus


def request_ring3_approval(tool_name: str, agent_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """Ring 3 tool: initiate IPC cross-review + human approval request.

    Returns {"approved": bool, "witness": str, "review_id": str}
    """
    bus = get_bus()
    msg = IPCMessage(
        sender=agent_id,
        receiver="broadcast",
        msg_type=MessageType.CROSS_REVIEW_REQ,
        payload={
            "task_id": f"ring3:{tool_name}",
            "changes": [{"tool": tool_name, "args": {k: str(v)[:100] for k, v in args.items()}}],
        },
    )
    result = bus.send(msg)
    review_id = result.get("msg_id", msg.msg_id)
    return {
        "approved": False,
        "witness": WitnessStatus.PENDING,
        "review_id": review_id,
        "status": WitnessStatus.AWAITING,
    }


def check_ring3_witness(review_id: str, agent_id: str) -> dict[str, Any]:
    """Check Ring 3 witness result."""
    bus = get_bus()
    msgs = bus.poll(agent_id)
    for msg in msgs:
        if msg.msg_type == MessageType.CROSS_REVIEW_RESP and msg.reply_to == review_id:
            return {
                "approved": msg.payload.get("approved", False),
                "witness": msg.sender,
                "comments": msg.payload.get("comments", ""),
                "review_id": review_id,
            }
    return {
        "approved": False,
        "witness": WitnessStatus.PENDING,
        "review_id": review_id,
        "status": WitnessStatus.STILL_WAITING,
    }
