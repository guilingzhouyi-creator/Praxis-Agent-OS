"""Terminal action handlers — registry + default implementations.
Extracted from agent_terminal.py for modularity.
"""
from __future__ import annotations

import logging
from typing import Any

from l1.kernel.discovery import get_tool_config
from l1.kernel.params.agent import (
    AGENT_LOOP_DEFAULT_STEPS,
    AGENT_LOOP_DEFAULT_TIMEOUT,
    CARD_TIMEOUT,
    TERMINAL_CONTEXT_RECENT,
)
from l1.kernel.params.api import SHELL_CMD_TIMEOUT
from l1.kernel.params.system import (
    LOG_TRUNC_40,
    LOG_TRUNC_200,
    LOG_TRUNC_300,
    LOG_TRUNC_1000,
    LOG_TRUNC_2000,
    LOG_TRUNC_3000,
    LOG_TRUNC_4000,
    POLL_INTERVAL_HANDLER,
    TERMINAL_OUTPUT_MAX_CHARS,
    TERMINAL_OUTPUT_MAX_LINES,
)
from l1.kernel.params.tool import TOOL_GREP_TIMEOUT
from l1.kernel.platform import grep_cmd as _grep_cmd

logger = logging.getLogger(__name__)


def _inject_enabled(domain: str) -> bool:
    """Whether the ``prompt.inject.<domain>`` system-prompt injection is on."""
    from l1.kernel.settings import inject_enabled as _ie

    return _ie(domain)

# ── Action handler registry (dual: method-name + function) ──

_ACTION_HANDLERS: dict[str, str] = {}
_FUNC_HANDLERS: dict[str, Any] = {}


def register_action(action: str, method_name: str) -> None:
    """Register a handler method name for an action."""
    _ACTION_HANDLERS[action] = method_name


def register_func_handler(action: str, handler_fn: Any) -> None:
    """Register a callable handler function for an action.

    External code can add custom tool handlers:
      from ._term_handlers import register_func_handler
      register_func_handler("my_tool", my_handler_fn)

    The handler receives (term, card, phases) and returns (output, findings, success).
    """
    _FUNC_HANDLERS[action] = handler_fn


def get_action_handler(term, action: str):
    """Resolve action → handler via ToolConfig first, then legacy registries."""
    try:
        from .tool_system.tool_config import ToolConfig as _TC
        from .tool_system.tool_policy import ToolPolicy as _TP
        if not _TP.is_allowed(term.agent_id, action):
            return None
        handler = _TC.resolve_handler(action)
        if handler:
            return lambda t, c, p: (handler(c.params or {}, t.agent_id), [], handler(c.params or {}, t.agent_id).get("success", True))
    except Exception:
        logger.debug("_term_handlers: handler resolution failed")
    direct_fn = _FUNC_HANDLERS.get(action)
    if direct_fn:
        return direct_fn
    direct = _ACTION_HANDLERS.get(action)
    if direct:
        return getattr(term, direct, None)
    for prefix, method in sorted(_ACTION_HANDLERS.items(), key=lambda x: -len(x[0])):
        if action.startswith(prefix):
            return getattr(term, method, None)
    fn = _HANDLER_MAP.get(action)
    if fn:
        return fn
    for prefix, fn in sorted(_HANDLER_MAP.items(), key=lambda x: -len(x[0])):
        if action.startswith(prefix):
            return fn
    return None


# ── Default handlers (extensible) ──

def handle_read_file(term, card, phases):
    cached = term.file_cache.get(card.target)
    if cached is not None:
        phases.append("cache_hit")
        return cached[:LOG_TRUNC_2000], [], True
    phases.append(f"execute:{card.action}")
    if card.action == "read_file":
        term.file_cache.set(card.target, f"executed {card.action} on {card.target}")
    return f"executed {card.action} on {card.target}", [], True


def handle_scout(term, card, phases):
    phases.append("scout")
    sr = term.scout_pool.commission(term.agent_id, card.target, card.params)
    return str(sr.get("output", [])), sr.get("findings", []), True


def handle_shell(term, card, phases):
    """Execute shell command with prompt, coloring, session support, structured errors."""
    import subprocess
    import time as _time

    from l1.kernel.platform import SHELL_PATH, SHELL_PROMPT

    command = card.params.get("command", card.target)
    timeout = int(card.params.get("timeout", CARD_TIMEOUT))
    session_id = card.params.get("session_id", "")
    show_prompt = card.params.get("prompt", True)

    if not command:
        return "no command specified", [], False

    shell_path = SHELL_PATH
    prompt_str = SHELL_PROMPT

    phases.append("shell")

    if session_id:
        try:
            from l3.shell import get_manager as _sh
            sm = _sh()
            existing = sm.get(session_id)
            if existing and existing.is_alive():
                sm.write(session_id, command + "\n")
                _time.sleep(POLL_INTERVAL_HANDLER)
                out = sm.get_output(session_id)
                output = "\n".join(out[-TERMINAL_OUTPUT_MAX_LINES:])[:TERMINAL_OUTPUT_MAX_CHARS]
                return f"{prompt_str}{command}\n{output}", [], True
        except Exception as e:
            return f"session error: {e}", [], False

    try:
        from l1.kernel.platform import run_shell
        r = run_shell(command, timeout=timeout)
        out = (r.stdout or "")[:LOG_TRUNC_3000]
        err = (r.stderr or "")[:LOG_TRUNC_1000]
        exit_code = r.returncode
        success = exit_code == 0
        result = (f"{prompt_str}{command}\n{out}")
        if err:
            result += f"\nstderr:\n{err}"
        if exit_code != 0:
            result += f"\nexit code: {exit_code}"
        phases.append(f"shell_done:{exit_code}")
        return result, [{"exit_code": exit_code, "stdout_len": len(r.stdout or ""),
                          "stderr_len": len(r.stderr or ""), "timed_out": False}], success
    except subprocess.TimeoutExpired:
        phases.append("shell_timeout")
        return f"{prompt_str}{command}\nTIMEOUT after {timeout}s", \
               [{"exit_code": -1, "timed_out": True, "timeout": timeout}], False
    except FileNotFoundError:
        phases.append("shell_not_found")
        return f"command not found: {command.split()[0]}", \
               [{"exit_code": -2, "error": "command not found"}], False
    except Exception as e:
        phases.append("shell_error")
        return str(e), [{"exit_code": -3, "error": str(e)}], False


def handle_write(term, card, phases):
    phases.append(f"execute:{card.action}")
    term.file_cache.invalidate(card.target)
    return f"executed {card.action} on {card.target}", [], True


def _handle_grep(args, agent):
    """Inline grep tool."""
    import subprocess as _sp
    cmd_list = _grep_cmd(args.get("pattern", ""), args.get("path", "."))
    try:
        r = _sp.run(cmd_list, capture_output=True, text=True, timeout=get_tool_config("grep_timeout", TOOL_GREP_TIMEOUT))
        out = (r.stdout or "")[:LOG_TRUNC_4000] or "no matches"
        return {"success": True, "data": out}
    except FileNotFoundError:
        return {"success": False, "error": "grep tool not found"}


def _handle_shell(args, agent):
    """Inline shell tool."""
    import subprocess as _sp

    from l1.kernel.platform import run_shell as _run_shell
    cmd = args.get("command", "")
    if not cmd:
        return {"success": False, "error": "command required"}
    try:
        r = _run_shell(cmd, timeout=SHELL_CMD_TIMEOUT)
        return {"success": r.returncode == 0, "stdout": r.stdout[:LOG_TRUNC_3000], "stderr": r.stderr[:LOG_TRUNC_1000], "exit_code": r.returncode}
    except _sp.TimeoutExpired:
        return {"success": False, "error": "timeout"}


def _handle_edit(args, agent):
    """Inline edit tool — replace old string with new."""
    path = args.get("path", "")
    old = args.get("old", "")
    new = args.get("new", "")
    if not path or not old:
        return {"success": False, "error": "path and old are required"}
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        if old not in content:
            return {"success": False, "error": f"pattern not found: {old[:LOG_TRUNC_40]}"}
        content = content.replace(old, new)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "resolved": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def handle_think(term, card, phases):
    phases.append("think")
    try:
        import os as _os

        from l3.memory.memory import get_memory

        from .agent_loop import AgentLoop

        task = card.params.get("prompt", card.target)

        # ── Inject OS-managed context from memory rings + context register ──
        # Gated by the prompt.inject.memory setting (user-configurable).
        memory = get_memory()
        ctx_parts = []
        from l1.kernel.params.system import CONTEXT_BUILD_MAX_TOKENS
        if _inject_enabled("memory"):
            # Task-aware injection: card metadata picks the dimension (execute→summary, decide→Mer, resume→layered)
            try:
                from l3.memory.memory_inject import build_context as _inject
                ring_context = _inject(term.agent_id, card=card,
                                       max_tokens=CONTEXT_BUILD_MAX_TOKENS,
                                       memory=memory)
            except Exception:
                ring_context = memory.build_context(
                    term.agent_id, max_tokens=CONTEXT_BUILD_MAX_TOKENS)
            if ring_context:
                ctx_parts.append(ring_context)
            recent = term.context.recent(TERMINAL_CONTEXT_RECENT)
            if recent:
                ctx_parts.append("=== Recent Context ===\n" + "\n".join(
                    str(r.get("value", ""))[:LOG_TRUNC_200] for r in recent
                ))
        memory_context = "\n\n".join(ctx_parts)

        from l1.kernel.prompts import get_prompt
        base_prompt = get_prompt("agent_terminal.think").format(
            agent_id=term.agent_id, role=term.role,
            task=task, territory=term.territory,
            tools=term.ring,
        )
        system_prompt = base_prompt
        if memory_context:
            from l1.kernel.prompts import get_prompt as _gp
            system_prompt += _gp("agent_terminal.memory_context", "").format(memory_context=memory_context)

        human_user = card.params.get("user_id", "")
        loop = AgentLoop(task=task, agent_id=term.agent_id, system=system_prompt,
                         user_id=human_user or term.agent_id, cell_id=term.cell_id)
        # Pass card-level gate_scope for GateChain enforcement
        gate_scope = card.params.get('_gate_scope', '') if hasattr(card, 'params') else ''
        if gate_scope:
            loop._gate_scope = gate_scope
        if getattr(term, '_pmu', None):
            loop.set_pmu(term._pmu)
        from l3.tool_system.tool_spec import is_muted as _is_muted

        _PROJECT_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", ".."))

        def _resolve(p):
            if _os.path.isabs(p): return p
            for c in [_os.path.join(_PROJECT_ROOT, p), _os.path.abspath(p)]:
                if _os.path.exists(c) or "write" in p: return c
            return _os.path.join(_PROJECT_ROOT, p)

        def _read(args, agent):
            p = args.get("path", ""); full = _resolve(p)
            try:
                with open(full, encoding="utf-8") as f:
                    return {"success": True, "data": f.read()[:LOG_TRUNC_4000], "resolved": full}
            except Exception as e:
                return {"success": False, "error": str(e)}

        def _write(args, agent):
            p, c = args.get("path", ""), args.get("content", "")
            full = _resolve(p)
            try:
                _os.makedirs(_os.path.dirname(_os.path.abspath(full)) or ".", exist_ok=True)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(c)
                term.file_cache.invalidate(p)
                return {"success": True, "resolved": full}
            except Exception as e:
                return {"success": False, "error": str(e)}

        def _list(args, agent):
            try:
                return {"success": True, "data": _os.listdir(_resolve(args.get("path", ".")))}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # ── Capability scoping: only register tools allowed by the step action ──
        allowed = card.params.get("_allowed_actions", [])
        def _scope(name: str) -> bool:
            return not allowed or name in allowed

        if _scope("read_file") and not _is_muted("read_file"):
            loop.add_tool("read_file", "Read file", {"path": "string"}, _read, parallel_safe=True)
        if _scope("grep_search") and not _is_muted("grep_search"):
            loop.add_tool("grep_search", "Grep search", {"pattern": "string", "path": "string"}, _handle_grep, parallel_safe=True)
        if _scope("list_dir") and not _is_muted("list_dir"):
            loop.add_tool("list_dir", "List directory", {"path": "string"}, _list, parallel_safe=True)
        if _scope("write_file") and not _is_muted("write_file"):
            loop.add_tool("write_file", "Write file", {"path": "string", "content": "string"}, _write)
        if _scope("edit") and not _is_muted("edit"):
            loop.add_tool("edit", "Edit file", {"path": "string", "old": "string", "new": "string"}, _handle_edit)
        if _scope("shell") and not _is_muted("shell"):
            loop.add_tool("shell", "Run shell command", {"command": "string"}, _handle_shell)

        # Pet watchdog before entering the long-running AgentLoop (multi-turn LLM)
        if getattr(term, '_watchdog_pet', None):
            term._watchdog_pet(term.agent_id)

        ar = loop.run(max_steps=AGENT_LOOP_DEFAULT_STEPS, timeout=AGENT_LOOP_DEFAULT_TIMEOUT,
                      model_config=term.model_config)

        # Store loop for persistent mode (reuse across cards)
        if getattr(term, '_persistent_loop', False):
            with term._active_loop_lock:
                term._active_loop = loop

        # Pet watchdog again after AgentLoop returns (before post-processing)
        if getattr(term, '_watchdog_pet', None):
            term._watchdog_pet(term.agent_id)

        # ── Collect multi tool_use → batch TerminalCard for Agent internal parallel ──
        batch_tool_calls = []
        for tc in ar.get("tool_call_results", []):
            if isinstance(tc, dict) and tc.get("name") and tc.get("input"):
                batch_tool_calls.append({"name": tc["name"], "input": tc["input"]})
        if len(batch_tool_calls) > 1:
            from ._term_types import TerminalCard as _TCCard
            term.stdin.append(_TCCard(action="batch", target=card.target or "", batch=batch_tool_calls))
            phases.append(f"batch_sent:{len(batch_tool_calls)}")

        output = ar.get("answer", "") or f"[AgentLoop] {len(ar.get('steps',[]))} steps"
        phases.append(f"agentloop:{len(ar.get('steps',[]))}steps")

        # Store thought result in memory (Ring 1) + context register
        memory.remember(
            agent_id=term.agent_id,
            entry_type="thought",
            content=f"{task}: {output[:LOG_TRUNC_300]}",
            tags=["think", card.action],
            ring=1,
        )
        term.context.store(key=f"think:{card.target[:LOG_TRUNC_40]}",
                           value={"agent": term.agent_id, "thought": card.target, "output": output[:LOG_TRUNC_200]},
                           agent_id=term.agent_id, entry_type="thought")
        phases.append("memory_stored")
        return output, [], True
    except Exception as e:
        return f"think error: {e}", [], False


# ── Handler dispatch map (legacy; prefer register_func_handler) ──

_HANDLER_MAP: dict[str, Any] = {
    "read_file": handle_read_file, "list_dir": handle_read_file,
    "grep_search": handle_read_file, "scout": handle_scout,
    "write_file": handle_write, "replace_string": handle_write,
    "delete": handle_write, "rename": handle_write,
    "think": handle_think,
    "shell": handle_shell, "run_in_terminal": handle_shell,
    "bash": handle_shell, "powershell": handle_shell,
    "exec": handle_shell, "execute": handle_shell,
}

# Register all built-in handlers via the public API for extensibility
for _action, _fn in list(_HANDLER_MAP.items()):
    if _action not in _FUNC_HANDLERS:
        _FUNC_HANDLERS[_action] = _fn
