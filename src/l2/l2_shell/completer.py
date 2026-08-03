"""Auto-completion for L2 Shell."""

from l1.kernel.commands import get_command, list_commands as _list_defs
from l1.kernel.params.system import SHELL_AUTOCOMPLETE_LIMIT, SHELL_AUTOCOMPLETE_AGENT_LIMIT


def autocomplete(line: str) -> list[dict]:
    """Return auto-completion suggestions for a partial L2 Shell command line.

    Matches:
      - ``/`` or empty → all commands
      - ``/prefix`` → commands starting with prefix
      - ``/cmd arg`` → agent / role completions for known commands

    Returns list of ``{"type", "value", "help", ...}`` dicts.
    """
    stripped = line.lstrip()
    cmds = _list_defs()
    results: list[dict] = []

    if not stripped or stripped == "/":
        for c in cmds:
            results.append({
                "type": "command", "value": f"/{c['name']}",
                "help": c["help"], "args": len(c.get("args", [])),
            })
        return results[:SHELL_AUTOCOMPLETE_LIMIT]

    if stripped.startswith("/"):
        parts = stripped[1:].split()
    else:
        parts = stripped.split()

    if len(parts) == 0:
        for c in cmds:
            results.append({
                "type": "command", "value": f"/{c['name']}",
                "help": c["help"],
            })
        return results[:SHELL_AUTOCOMPLETE_LIMIT]

    cmd_name = parts[0].lower()
    cmd_info = get_command(cmd_name)

    if len(parts) == 1:
        partial = parts[0].lower()
        for c in cmds:
            if c["name"].startswith(partial):
                results.append({
                    "type": "command", "value": f"/{c['name']}",
                    "help": c["help"], "args": len(c.get("args", [])),
                })
        return results[:SHELL_AUTOCOMPLETE_LIMIT]

    if cmd_info and cmd_name in ("connect", "spawn", "kill", "destroy", "card", "memory", "tokens"):
        arg_idx = len(parts) - 1
        partial = parts[-1]

        if arg_idx <= 1:
            suggestions = _complete_agent(partial, cmd_name)
            results.extend(suggestions)
            if results:
                return results[:SHELL_AUTOCOMPLETE_AGENT_LIMIT]

        if arg_idx == 2:
            role_suggestions = _complete_role(partial)
            results.extend(role_suggestions)
            return results[:SHELL_AUTOCOMPLETE_AGENT_LIMIT]

    return []


def _complete_agent(partial: str, cmd_name: str = "") -> list[dict]:
    """Complete agent IDs matching *partial*.  Falls back to current state agent."""
    from .state import get_state
    state = get_state()
    results = []
    try:
        from l3.agent_terminal import get_terminals
        agents = list(get_terminals().keys())
    except Exception:
        logger.warning("completer: get_terminals failed, falling back to state agent_id")
        agents = [state.agent_id] if state.agent_id else []

    for aid in agents:
        if partial and not aid.startswith(partial) and partial not in aid:
            continue
        label = aid.replace("agent-", "")
        results.append({"type": "agent", "value": aid, "help": f"agent: {label}"})
    return results


def _complete_role(partial: str) -> list[dict]:
    """Complete role names matching *partial* from CENTRAL_ROLES.

    Excludes the ``default`` role — it is a fallback, not a connectable role.
    """
    from l1.kernel.params.agent import CENTRAL_ROLES
    roles = [r for r in CENTRAL_ROLES if r != "default"]
    partial_l = partial.lower()
    return [{"type": "role", "value": r, "help": f"role: {r}"}
            for r in roles if not partial or r.lower().startswith(partial_l)]
