"""Peer agent communication handlers."""

try:
    from services.ipc import get_bus, IPCMessage, MessageType
    HAS_IPC = True
except ImportError:
    HAS_IPC = False

try:
    from services.cell import get_cell
    HAS_CELL = True
except ImportError:
    HAS_CELL = False


def agent_list(args: dict, agent_id: str) -> dict:
    if HAS_CELL:
        try:
            cell = get_cell()
            agents = cell.list_agents() if hasattr(cell, "list_agents") else []
            return {"success": True, "agents": agents}
        except Exception as e:
            return {"success": False, "error": str(e)}
    return {"success": True, "agents": [], "note": "cell not available"}


def agent_heartbeat(args: dict, agent_id: str) -> dict:
    target = args.get("target", "")
    if not target:
        return {"success": True, "status": "alive", "agent_id": agent_id}
    if HAS_IPC:
        try:
            bus = get_bus()
            msg = IPCMessage(sender=agent_id, receiver=target, msg_type=MessageType.KEEPALIVE, payload={})
            bus.send(msg)
            return {"success": True, "status": "ping_sent", "target": target}
        except Exception as e:
            return {"success": False, "error": str(e)}
    return {"success": True, "status": "alive", "note": "ipc not available"}


def agent_message(args: dict, agent_id: str) -> dict:
    target = args.get("target", "")
    message = args.get("message", "")
    if not target or not message:
        return {"success": False, "error": "target and message are required"}
    if HAS_IPC:
        try:
            bus = get_bus()
            msg = IPCMessage(sender=agent_id, receiver=target, msg_type=MessageType.DIRECT_MESSAGE, payload={"text": message})
            bus.send(msg)
            return {"success": True, "target": target}
        except Exception as e:
            return {"success": False, "error": str(e)}
    return {"success": False, "error": "ipc not available"}
