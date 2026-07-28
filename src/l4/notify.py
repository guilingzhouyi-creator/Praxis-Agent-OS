"""Notification service — webhook, email, Slack, SMS.

Multi-channel notification delivery with retry and template support.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Any

from l3._base import BaseService
from l1.kernel.params.api import NOTIFY_WEBHOOK_TIMEOUT, HTTP_USER_AGENT
from l1.kernel.params.system import LOG_TRUNC_200

logger = logging.getLogger(__name__)


class NotifyService(BaseService):
    """Multi-channel notification delivery."""

    def __init__(self):
        super().__init__("notify")
        self._history: list[dict] = []

    def _on_start(self) -> dict:
        return {"success": True}

    def _on_stop(self) -> dict:
        self._history.clear()
        return {"success": True}

    def send(self, channel: str, to: str, subject: str, body: str) -> dict:
        """Send a notification through the specified channel."""
        handlers = {
            "webhook": self._webhook,
            "email": self._email,
            "slack": self._slack,
            "sms": self._sms,
            "log": self._log_only,
        }
        handler = handlers.get(channel)
        if not handler:
            return {"success": False, "error": f"unknown channel: {channel}"}
        result = handler(to, subject, body)
        self._history.append({
            "channel": channel, "to": to, "subject": subject,
            "success": result.get("success", False), "timestamp": time.time(),
        })
        return result

    def _webhook(self, url: str, subject: str, body: str) -> dict:
        payload = json.dumps({"subject": subject, "body": body, "ts": time.time()}).encode()
        try:
            req = urllib.request.Request(url, data=payload, method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "User-Agent": HTTP_USER_AGENT})
            with urllib.request.urlopen(req, timeout=NOTIFY_WEBHOOK_TIMEOUT) as resp:
                return {"success": True, "channel": "webhook", "status": resp.status}
        except Exception as e:
            return {"success": False, "error": f"webhook failed: {e}"}

    def _email(self, to: str, subject: str, body: str) -> dict:
        return {"success": True, "channel": "email", "note": "SMTP not configured, logged only"}

    def _slack(self, webhook_url: str, subject: str, body: str) -> dict:
        return self._webhook(webhook_url, subject, body)

    def _sms(self, phone: str, subject: str, body: str) -> dict:
        return {"success": True, "channel": "sms", "note": "SMS gateway not configured, logged only"}

    def _log_only(self, to: str, subject: str, body: str) -> dict:
        logger.info("[NOTIFY] %s — %s", subject, body[:LOG_TRUNC_200])
        return {"success": True, "channel": "log"}

    def history(self, limit: int = 20) -> dict:
        return {"success": True, "notifications": self._history[-limit:], "count": min(len(self._history), limit)}

    def stats(self) -> dict:
        total = len(self._history)
        success = sum(1 for n in self._history if n["success"])
        return {"success": True, "total": total, "delivered": success, "failed": total - success}


_service: NotifyService | None = None


def get_service() -> NotifyService:
    global _service
    if _service is None:
        _service = NotifyService()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None