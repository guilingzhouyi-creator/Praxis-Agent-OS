"""Task completion bus — webhook dispatch on card lifecycle events.

Design:
  - Subscribers register URL + optional filters (card_type, domain, result pattern)
  - On CardRegistry.complete() → dispatch to all matching subscribers
  - Retry with exponential backoff (3 attempts: 1s → 4s → 10s)
  - Non-blocking: webhook dispatch runs in background thread
  - Configurable via praxis.yaml → webhooks: section

Usage:
  from services.task_bus import get_task_bus
  bus = get_task_bus()
  bus.register("my-ci", "http://ci.example.com/webhook", filters=["domain=deploy"])
  # Now every completed card with domain="deploy" POSTs to that URL
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request as req
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Callable

from kernel.params import PRAXIS_DATA_DIR

logger = logging.getLogger(__name__)

_WEBHOOK_MAX_RETRIES = 3
_WEBHOOK_BACKOFF = [1.0, 4.0, 10.0]
_WEBHOOK_TIMEOUT = 15


@dataclass
class WebhookSubscriber:
    """A registered webhook endpoint."""
    name: str
    url: str
    secret: str = ""                      # HMAC secret for signature
    filters: dict[str, str] = field(default_factory=dict)  # e.g. {"domain": "deploy"}
    retries: int = _WEBHOOK_MAX_RETRIES
    enabled: bool = True


# ── Payload schema ──

def _build_payload(card_id: str, state: str, card_data: dict | None = None) -> str:
    """Build JSON payload for webhook POST."""
    payload = {
        "event": "card.completed",
        "card_id": card_id,
        "state": state,
        "timestamp": time.time(),
    }
    if card_data:
        payload["card"] = {
            "intent": card_data.get("intent", ""),
            "domain": card_data.get("domain", ""),
            "result": card_data.get("result", {}),
            "error": card_data.get("error", ""),
            "elapsed": card_data.get("elapsed", 0),
        }
    return json.dumps(payload, ensure_ascii=False)


# ── TaskBus ──

class TaskBus:
    """Manages webhook subscribers and dispatches completion events."""

    def __init__(self):
        self._subscribers: dict[str, WebhookSubscriber] = {}
        self._lock = threading.Lock()
        self._load_config()

    def _load_config(self) -> None:
        """Load webhook subscribers from praxis.yaml."""
        try:
            from services.config_loader import load as load_config
            cfg = load_config()
            hooks = cfg.get("webhooks", {})
            if isinstance(hooks, dict):
                for name, info in hooks.items():
                    if isinstance(info, dict) and info.get("url"):
                        self._subscribers[name] = WebhookSubscriber(
                            name=name,
                            url=info["url"],
                            secret=info.get("secret", ""),
                            filters=info.get("filters", {}),
                            retries=info.get("retries", _WEBHOOK_MAX_RETRIES),
                            enabled=info.get("enabled", True),
                        )
                        logger.info("task_bus: loaded webhook '%s' → %s", name, info["url"])
        except Exception as e:
            logger.warning("task_bus: config load failed: %s", e)

    def register(self, name: str, url: str, secret: str = "",
                 filters: dict[str, str] | None = None,
                 retries: int = _WEBHOOK_MAX_RETRIES) -> dict:
        """Register a webhook subscriber."""
        if not url.startswith(("http://", "https://")):
            return {"success": False, "error": f"invalid URL: {url}"}
        with self._lock:
            self._subscribers[name] = WebhookSubscriber(
                name=name, url=url, secret=secret,
                filters=filters or {}, retries=retries,
            )
        logger.info("task_bus: registered '%s' → %s", name, url)
        return {"success": True, "name": name, "url": url}

    def unregister(self, name: str) -> dict:
        """Remove a webhook subscriber."""
        with self._lock:
            if name not in self._subscribers:
                return {"success": False, "error": f"unknown subscriber: {name}"}
            del self._subscribers[name]
        return {"success": True, "name": name}

    def list(self) -> list[dict]:
        """List all registered webhook subscribers."""
        with self._lock:
            return [
                {"name": n, "url": s.url, "enabled": s.enabled,
                 "filters": s.filters}
                for n, s in sorted(self._subscribers.items())
            ]

    def dispatch(self, card_id: str, state: str,
                 card_data: dict | None = None) -> int:
        """Dispatch a card completion event to all matching webhooks.

        Returns the number of webhooks that were triggered.
        Runs asynchronously in a background thread.
        """
        with self._lock:
            targets = [
                s for s in self._subscribers.values()
                if s.enabled and self._matches_filters(s, card_data or {})
            ]
        if not targets:
            return 0
        payload = _build_payload(card_id, state, card_data)
        thread = threading.Thread(
            target=self._dispatch_all,
            args=(targets, payload),
            daemon=True,
        )
        thread.start()
        return len(targets)

    def _matches_filters(self, sub: WebhookSubscriber, card_data: dict) -> bool:
        """Check if card data matches subscriber's filters."""
        if not sub.filters:
            return True
        for key, expected in sub.filters.items():
            actual = str(card_data.get(key, ""))
            if actual != expected:
                return False
        return True

    def _dispatch_all(self, targets: list[WebhookSubscriber],
                      payload: str) -> None:
        """Send webhook POST to all targets with retry."""
        for sub in targets:
            self._dispatch_one(sub, payload)

    def _dispatch_one(self, sub: WebhookSubscriber, payload: str) -> bool:
        """Send one webhook POST with exponential backoff retry."""
        for attempt in range(sub.retries):
            try:
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": "Praxis-TaskBus/1.0",
                }
                if sub.secret:
                    import hmac, hashlib
                    sig = hmac.new(
                        sub.secret.encode(), payload.encode(), hashlib.sha256
                    ).hexdigest()
                    headers["X-Praxis-Signature"] = sig
                r = req.urlopen(
                    req.Request(sub.url, data=payload.encode(), headers=headers,
                                method="POST"),
                    timeout=_WEBHOOK_TIMEOUT,
                )
                logger.info("task_bus: delivered to '%s' (HTTP %d)",
                            sub.name, r.status)
                return True
            except (urllib.error.HTTPError, urllib.error.URLError,
                    OSError) as e:
                if attempt < sub.retries - 1:
                    backoff = _WEBHOOK_BACKOFF[min(attempt, len(_WEBHOOK_BACKOFF) - 1)]
                    logger.warning("task_bus: retry %d/%d for '%s' in %.1fs: %s",
                                   attempt + 1, sub.retries, sub.name, backoff, e)
                    time.sleep(backoff)
                else:
                    logger.error("task_bus: failed to deliver to '%s' after %d attempts: %s",
                                 sub.name, sub.retries, e)
        return False


_bus: TaskBus | None = None


def get_task_bus() -> TaskBus:
    """Get singleton TaskBus instance."""
    global _bus
    if _bus is None:
        _bus = TaskBus()
    return _bus


def reset_task_bus() -> None:
    """Reset singleton (for testing)."""
    global _bus
    _bus = None
