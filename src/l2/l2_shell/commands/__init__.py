"""L2 Shell command handlers — split package.

Backward-compatible re-exports:
  from l2.l2_shell.commands import preconnect_enhanced
continues to work after the monolithic commands.py was split.
"""

from __future__ import annotations

import logging

from l1.kernel.commands import get_handler as _gh
from l1.kernel.commands import get_registry
from l3.error_bus import capture

logger = logging.getLogger(__name__)

_registry = get_registry()

# ── Import sub-modules to register their @system_command handlers ──
from . import (
    ci,  # noqa: F401
    connect,  # noqa: F401
    extra,  # noqa: F401
    harness,  # noqa: F401
    l3a,  # noqa: F401
    memory,  # noqa: F401
    model,  # noqa: F401
    system,  # noqa: F401
    test_auto,  # noqa: F401
)

# ── Backward-compatible re-exports ──
from .common import (
    _coerce,
    _list_defs,
    _parse_agent_ref,
    _register_handler,
    list_commands,
    preconnect_enhanced,
    resolve_agents,
    resolve_scope,
)
from .connect import (
    _cmd_agents,
    _cmd_connect,
    _cmd_disconnect,
    _cmd_mode,
)
from .extra import (
    _cmd_buffer,
    _cmd_cells,
    _cmd_cluster,
    _cmd_cross,
    _cmd_htn,
    _cmd_mcp,
    _cmd_security,
)
from .l3a import (
    _cmd_l3a,
)
from .memory import (
    _cmd_agent_refresh,
    _cmd_agent_restart,
    _cmd_audit,
    _cmd_card,
    _cmd_cell_create,
    _cmd_destroy,
    _cmd_emergency,
    _cmd_kill,
    _cmd_memory,
    _cmd_plugins,
    _cmd_spawn,
    _cmd_tokens,
)
from .model import (
    _cmd_config,
    _cmd_cron,
    _cmd_model,
    _cmd_settings,
)
from .system import (
    _cmd_cache,
    _cmd_clear,
    _cmd_devices,
    _cmd_help,
    _cmd_history,
    _cmd_intents,
    _cmd_lang,
    _cmd_observe,
    _cmd_process,
    _cmd_scheduler,
    _cmd_skills,
    _cmd_status,
    _cmd_sysinfo,
    _cmd_tools,
    _cmd_vfs,
)


# ── _pipeline (shared, inlined) ──
def _pipeline(segments: list[str]) -> dict:
    """Execute a command pipeline: cmd1 | cmd2.
    Maps first command's output as second command's input.
    """
    from .common import _pipeline
    return _pipeline(segments)

# ── Auto-register all _cmd_* functions ──
# This must run AFTER all sub-modules are imported.
import sys as _sys

_SYSTEM_COMMANDS: list[tuple[str, callable, dict]] = []

for _module_name in ("common", "connect", "system", "memory", "model", "extra",
                     "harness", "l3a", "test_auto", "ci"):
    _mod = _sys.modules.get(f"l2.l2_shell.commands.{_module_name}")
    if _mod is None:
        continue
    for _attr in dir(_mod):
        if _attr.startswith("_cmd_"):
            _fn = getattr(_mod, _attr, None)
            if callable(_fn) and getattr(_fn, "__name__", "") == _attr:
                _SYSTEM_COMMANDS.append((_attr[5:], _fn, {}))

# Load command definitions from commands.yaml
try:
    _reg = get_registry()
    _reg.load_defaults()
except Exception:
    logger.warning("failed to load default commands from commands.yaml")
    capture("load default commands failed", error_code="E_CMD_INIT", component="l2")

_registered_names: set[str] = set()
for _name, _fn, _meta in _SYSTEM_COMMANDS:
    if _name in _registered_names:
        # Duplicate definitions across sub-modules (e.g. _cmd_help in
        # connect.py and system.py) — register only the first occurrence.
        continue
    _registered_names.add(_name)
    try:
        _reg.register_system(_name, _fn, metadata=_meta or None)
    except Exception as _e:
        logger.warning("command registration failed: %s: %s", _name, _e)
