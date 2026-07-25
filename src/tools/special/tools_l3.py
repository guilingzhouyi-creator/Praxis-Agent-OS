"""L3 tools — intent parsing, card creation, dependency chain.

Integrates with the main card pipeline (l3a + CardRegistry) instead of
maintaining a separate card system.

Keeps the keyword-based domain inference logic but routes cards through:
  l3a.TaskCard / l3a.CardType → CardRegistry → Cell → AgentTerminal
"""

from __future__ import annotations

import logging
import time
from typing import Any

from kernel.params import TOOL_L3_LIST_LIMIT

from services.l3a import TaskCard, CardType
from services.card_registry import get_registry

logger = logging.getLogger(__name__)

# Domain keywords
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "config":   ["config", "configuration", "settings", ".env"],
    "routes":   ["route", "endpoint", "api", "url"],
    "pages":    ["page", "template", "html", "view"],
    "services": ["service", "business", "logic", "backend"],
    "middleware": ["middleware", "filter", "intercept"],
    "auth":     ["auth", "login", "register", "permission"],
    "i18n":     ["i18n", "locale", "translation", "language"],
    "tests":    ["test", "unittest", "pytest", "spec"],
    "security": ["security", "encrypt", "vulnerability", "crypto"],
    "docs":     ["doc", "documentation", "readme", "guide"],
}


def _keyword_match(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(kw.lower() in t for kw in keywords)


def _infer_domain(intent: str) -> str:
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if _keyword_match(intent, keywords):
            return domain
    return ""


def _card_type_from_text(text: str) -> int:
    if text.startswith("!"):
        return CardType.DIRECT_SESSION.value
    if "?" in text or "\u8ba8\u8bba" in text or "\u5efa\u8bae" in text:
        return CardType.ISSUE.value
    return CardType.EXECUTION.value


# ── 1. Intent parsing → CardRegistry ──

def _cmd_intent_parse(args: dict, agent_id: str) -> dict:
    """Parse natural language intent → submit to CardRegistry."""
    text = args.get("text", "")
    if not text:
        return {"success": False, "error": "text is required"}
    domain = _infer_domain(text)
    ct_value = _card_type_from_text(text)
    ct = CardType.EXECUTION if ct_value == CardType.EXECUTION.value else \
         CardType.ISSUE if ct_value == CardType.ISSUE.value else \
         CardType.DIRECT_SESSION
    reg = get_registry()
    cid = reg.submit(text, domain=domain)
    return {"success": True, "data": {"card_id": cid, "domain": domain, "card_type": ct.name}}


def _cmd_intent_classify(args: dict, agent_id: str) -> dict:
    """Classify intent type."""
    text = args.get("text", "")
    if not text:
        return {"success": False, "error": "text is required"}
    ct = _card_type_from_text(text)
    return {"success": True, "data": {"text": text[:100], "card_type": ct, "confidence": 0.85}}


def _cmd_intent_decompose(args: dict, agent_id: str) -> dict:
    """Decompose compound intent into sub-card chain via CardRegistry."""
    text = args.get("text", "")
    if not text:
        return {"success": False, "error": "text is required"}
    parts = [p.strip() for p in text.replace("\u5148", "").replace("\u518d", "").split("\u7136\u540e")]
    reg = get_registry()
    sub_ids = []
    for i, part in enumerate(parts):
        if not part:
            continue
        domain = _infer_domain(part)
        cid = reg.submit(part, domain=domain, priority=3 + i)
        sub_ids.append({"card_id": cid, "intent": part[:40], "domain": domain})
    return {"success": True, "data": {"original": text, "sub_cards": sub_ids, "count": len(sub_ids)}}


# ── 2. Card creation → CardRegistry ──

def _cmd_card_create(args: dict, agent_id: str) -> dict:
    """Create a card through CardRegistry."""
    intent = args.get("intent", "")
    domain = args.get("domain", "") or _infer_domain(intent)
    priority = args.get("priority", 5)
    if not intent:
        return {"success": False, "error": "intent is required"}
    cid = get_registry().submit(intent, domain=domain, priority=priority)
    return {"success": True, "data": {"card_id": cid, "domain": domain, "priority": priority}}


def _cmd_card_status(args: dict, agent_id: str) -> dict:
    """Query card status from CardRegistry."""
    card_id = args.get("card_id", "")
    reg = get_registry()
    if not card_id:
        cards = reg.list(limit=TOOL_L3_LIST_LIMIT)
        return {"success": True, "data": {"cards": cards, "count": len(cards)}}
    record = reg.get(card_id)
    if not record:
        return {"success": False, "error": "card not found"}
    return {"success": True, "data": {
        "card_id": record.id, "intent": record.intent, "domain": record.domain,
        "state": record.state.name, "error": record.error,
    }}


# ── Tool registry ──

TOOLS = {
    "intent_parse": {"func": _cmd_intent_parse, "params": ["text"], "danger": 0,
                     "desc": "Parse natural language intent into a card via CardRegistry"},
    "intent_classify": {"func": _cmd_intent_classify, "params": ["text"], "danger": 0,
                        "desc": "Classify intent type"},
    "intent_decompose": {"func": _cmd_intent_decompose, "params": ["text"], "danger": 1,
                         "desc": "Decompose compound intent into sub-cards"},
    "card_create": {"func": _cmd_card_create, "params": ["intent", "domain", "priority"], "danger": 1,
                    "desc": "Create a task card"},
    "card_status": {"func": _cmd_card_status, "params": ["card_id"], "danger": 0,
                    "desc": "Query card status"},
}


def execute_l3_tool(tool_name: str, args: dict, agent_id: str = "l3") -> dict:
    tool = TOOLS.get(tool_name)
    if not tool:
        return {"success": False, "error": f"unknown L3 tool: {tool_name}"}
    try:
        return tool["func"](args, agent_id)
    except Exception as e:
        return {"success": False, "error": str(e)}


def execute_l3_parse(text: str) -> dict:
    return _cmd_intent_parse({"text": text}, "l3")


def register_tools() -> None:
    from services.tool_spec import ToolSpec, ParamSpec, register, ToolRing as R
    for name, t in TOOLS.items():
        params = [ParamSpec(p, "string", required=(p in t.get("params", []))) for p in t.get("params", [])]
        register(ToolSpec(name=name, description=t["desc"], category="generic",
                          ring=R.RING_1, danger=t.get("danger", 0),
                          parameters=params, handler=t["func"]))
