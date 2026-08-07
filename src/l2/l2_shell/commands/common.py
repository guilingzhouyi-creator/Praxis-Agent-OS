"""Shared utilities — value coercion, pipeline, agent resolution."""
from __future__ import annotations

import logging
import shlex
from typing import Any

from l1.kernel.commands import get_handler as _gh
from l1.kernel.commands import get_registry
from l1.kernel.params.agent import DEFAULT_CELL_ID

logger = logging.getLogger(__name__)

_registry = get_registry()


def _coerce(value: str) -> Any:
    """Coerce string values to int/float/bool when appropriate."""
    if value.lower() in ("true", "yes"):
        return True
    if value.lower() in ("false", "no"):
        return False
    try:
        return int(value)
    except ValueError:
        logger.debug("commands: %r not an int, trying float", value)
    try:
        return float(value)
    except ValueError:
        logger.debug("commands: %r not numeric, returning string", value)
    return value


def _parse_agent_ref(arg: str) -> tuple[str, str]:
    """Parse 'cell.agent' or bare 'agent' into (cell_id, agent_id)."""
    if "." in arg:
        parts = arg.split(".", 1)
        return parts[0], parts[1]
    return DEFAULT_CELL_ID, arg


def _register_handler(name: str, handler: Any, metadata: dict | None = None) -> None:
    _registry.register_system(name, handler, metadata)


def _list_defs() -> list[dict]:
    return _registry.list()


def preconnect_enhanced(cell_id: str, agent_id: str, message: str = "") -> dict:
    """Run a preconnect check that also verifies the LLM provider status."""
    from l2.selector import preconnect as _preconnect
    checks = {}
    basic = _preconnect(cell_id, agent_id, message)
    checks["preconnect"] = basic
    if not basic.get("allowed"):
        return {"allowed": False, "checks": checks, "reason": basic.get("reason", "preconnect_failed")}
    try:
        from l3.services.adapter_bridge import get_llm_engine
        engine = get_llm_engine()
        provider_status = engine.provider_status() if hasattr(engine, 'provider_status') else {}
        checks["llm_provider"] = provider_status
        if provider_status.get("status") == "error":
            return {"allowed": False, "checks": checks, "reason": f'llm_provider_error: {provider_status.get("error", "")}'}
    except ImportError:
        checks["llm_provider"] = {"status": "error", "error": "llm module not available"}
        return {"allowed": False, "checks": checks, "reason": "llm_module_missing"}
    except AttributeError as e:
        checks["llm_provider"] = {"status": "error", "error": str(e)}
        return {"allowed": False, "checks": checks, "reason": f'llm_api_mismatch: {e}'}
    except Exception as e:
        checks["llm_provider"] = {"status": "error", "error": str(e)}
        return {"allowed": False, "checks": checks, "reason": f'llm_unavailable: {e}'}
    return {"allowed": True, "checks": checks}


def list_commands() -> list[dict]:
    """Return all registered commands formatted for shell autocomplete/help."""
    return [{"command": f"/{c['name']}", "help": c["help"], "aliases": c.get("aliases", []),
             "category": c.get("category", "other"), "args": c.get("args", []),
             "examples": c.get("examples", [])} for c in _list_defs()]


def resolve_scope(args: list[str]) -> tuple[str, str, list[str]]:
    """Resolve the leading scope (global/cell/agent) from shell arguments."""
    if not args:
        return ("global", "", [])
    head = args[0]
    if head == "global" or head.startswith("--"):
        return ("global", "", args)
    if head == "cell" and len(args) >= 2:
        return ("cell", args[1], args[2:])
    if head == "agent" and len(args) >= 2:
        return ("agent", args[1], args[2:])
    return ("global", "", args)


def resolve_agents(scope: str, scope_id: str) -> list[str]:
    """Resolve the agent ids matching a scope (agent/cell/global)."""
    from l3.agent_terminal import get_terminals
    terms = get_terminals()
    if scope == "agent":
        return [scope_id] if scope_id in terms else []
    if scope == "cell":
        try:
            from l3.cell import get_cell
            cell = get_cell(scope_id)
            return list(cell._agents.keys()) if hasattr(cell, '_agents') else []
        except Exception:
            return []
    return list(terms.keys())


def _pipeline(segments: list[str]) -> dict:
    """Execute a command pipeline: cmd1 | cmd2."""
    segment_results: list[dict] = []
    for i, segment in enumerate(segments):
        segment = segment.strip()
        parts = shlex.split(segment)
        if not parts:
            continue
        cmd = parts[0].lstrip("/")
        args = parts[1:]
        if i > 0 and segment_results:
            prev = segment_results[-1]
            if isinstance(prev, dict) and "output" in prev:
                args = [prev["output"]] + args
        handler = _gh(cmd)
        if handler:
            try:
                result = handler(args)
                segment_results.append(result)
            except Exception as e:
                return {"success": False, "error": f"pipeline step {i} '{cmd}' failed: {e}"}
        else:
            return {"success": False, "error": f"pipeline step {i}: unknown command: {cmd}"}
    return segment_results[-1] if segment_results else {"success": True, "output": ""}
