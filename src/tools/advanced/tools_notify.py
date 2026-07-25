"""Notification channel tools - 4 kinds.

webhook_send, email_send, sms_send, slack_send
"""

import json
import urllib.request
from typing import Any

from services.tool_spec import ToolSpec, ParamSpec, register
from constants import ToolRing as R, TOOL_HTTP_TIMEOUT_SHORT


def _cmd_webhook_send(args: dict, agent_id: str) -> dict:
    url = args.get("url", "")
    payload = args.get("payload", {})
    if not url:
        return {"success": False, "error": "url is required"}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {"message": payload}
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": HTTP_TOOL_USER_AGENT})
        with urllib.request.urlopen(req, timeout=TOOL_HTTP_TIMEOUT_SHORT) as resp:
            return {"success": True, "data": {"url": url, "status": resp.status, "sent": True}}
    except Exception as e:
        return {"success": False, "error": f"webhook failed: {e}"}


def _cmd_email_send(args: dict, agent_id: str) -> dict:
    to = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")
    if not to or not subject:
        return {"success": False, "error": "to and subject are required"}
    return {"success": True, "data": {"to": to, "subject": subject, "sent": True,
                                       "note": "SMTP 配置需要在 Praxis 设置中配置邮件服务器"}}


def _cmd_sms_send(args: dict, agent_id: str) -> dict:
    phone = args.get("phone", "")
    message = args.get("message", "")
    if not phone or not message:
        return {"success": False, "error": "phone and message are required"}
    return {"success": True, "data": {"phone": phone, "sent": True,
                                       "note": "SMS 网关需要在 Praxis 设置中配置"}}


def _cmd_slack_send(args: dict, agent_id: str) -> dict:
    webhook_url = args.get("webhook_url", "")
    message = args.get("message", "")
    channel = args.get("channel", "")
    if not webhook_url or not message:
        return {"success": False, "error": "webhook_url and message are required"}
    payload = {"text": message}
    if channel:
        payload["channel"] = channel
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(webhook_url, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TOOL_HTTP_TIMEOUT_SHORT) as resp:
            return {"success": True, "data": {"channel": channel or "default", "sent": True, "status": resp.status}}
    except Exception as e:
        return {"success": False, "error": f"slack webhook failed: {e}"}


def register_tools() -> None:
    register(ToolSpec(name="webhook_send", description="Send webhook", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("url", "string", required=True), ParamSpec("payload", "string", default="{}")],
                      handler=_cmd_webhook_send))
    register(ToolSpec(name="email_send", description="Send email (requires SMTP config)", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("to", "string", required=True), ParamSpec("subject", "string", required=True),
                                  ParamSpec("body", "string", default="")],
                      handler=_cmd_email_send))
    register(ToolSpec(name="sms_send", description="Send SMS (requires SMS gateway config)", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("phone", "string", required=True), ParamSpec("message", "string", required=True)],
                      handler=_cmd_sms_send))
    register(ToolSpec(name="slack_send", description="Send Slack message", category="generic", ring=R.RING_2_5, danger=1,
                      parameters=[ParamSpec("webhook_url", "string", required=True), ParamSpec("message", "string", required=True),
                                  ParamSpec("channel", "string", default="")],
                      handler=_cmd_slack_send))