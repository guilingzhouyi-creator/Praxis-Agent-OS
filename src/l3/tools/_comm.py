"""Communication tool handlers."""

try:
    from l4.notify import send_notification
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False


def ask_user(args: dict, agent_id: str) -> dict:
    question = args.get("question", "")
    if not question:
        return {"success": False, "error": "question is required"}
    if HAS_NOTIFY:
        send_notification(agent_id, f"[ASK] {question}")
    return {"success": True, "question": question, "instruction": "Awaiting user reply. Use the reply when available."}


def confirm(args: dict, agent_id: str) -> dict:
    message = args.get("message", "")
    if not message:
        return {"success": False, "error": "message is required"}
    if HAS_NOTIFY:
        send_notification(agent_id, f"[CONFIRM] {message}")
    return {"success": True, "message": message, "instruction": "Awaiting user confirmation."}


def notify(args: dict, agent_id: str) -> dict:
    message = args.get("message", "")
    if not message:
        return {"success": False, "error": "message is required"}
    if HAS_NOTIFY:
        send_notification(agent_id, f"[NOTIFY] {message}")
    return {"success": True, "message": message}
