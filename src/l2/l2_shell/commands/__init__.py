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
from . import connect   # noqa: F401
from . import system    # noqa: F401
from . import memory    # noqa: F401
from . import model     # noqa: F401
from . import extra     # noqa: F401
from . import l3a       # noqa: F401

# ── Backward-compatible re-exports ──
from .common import (
    _coerce, _parse_agent_ref, _register_handler, _list_defs,
    preconnect_enhanced, list_commands, resolve_scope, resolve_agents,
)
from .connect import (
    _cmd_connect, _cmd_disconnect, _cmd_mode, _cmd_agents,
)
from .system import (
    _cmd_help, _cmd_status, _cmd_process, _cmd_devices, _cmd_vfs,
    _cmd_sysinfo, _cmd_clear, _cmd_history, _cmd_lang, _cmd_tools,
    _cmd_cache, _cmd_observe, _cmd_skills, _cmd_intents, _cmd_scheduler,
)
from .memory import (
    _cmd_memory, _cmd_card, _cmd_plugins, _cmd_spawn, _cmd_kill,
    _cmd_destroy, _cmd_emergency, _cmd_audit,
    _cmd_tokens, _cmd_agent_restart, _cmd_agent_refresh,
    _cmd_cell_create,
)
from .model import (
    _cmd_model, _cmd_config, _cmd_cron, _cmd_settings,
)
from .extra import (
    _cmd_cluster, _cmd_htn, _cmd_cross, _cmd_buffer,
    _cmd_security, _cmd_mcp, _cmd_cells,
)
from .l3a import (
    _cmd_l3a,
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

for _module_name in ("common", "connect", "system", "memory", "model", "extra", "l3a"):
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

for _name, _fn, _meta in _SYSTEM_COMMANDS:
    try:
        _reg.register_system(_name, _fn, metadata=_meta or None)
    except Exception as _e:
        logger.warning("command registration failed: %s: %s", _name, _e)
