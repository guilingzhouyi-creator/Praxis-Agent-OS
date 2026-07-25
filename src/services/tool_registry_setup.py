"""Tool registry — auto-discovers and registers all tools_*.py modules.

Each tools_*.py should implement a register_tools() function.
Tools are organized into four category directories under tools/:
  - tools/base/     — Ring 1 read-only tools
  - tools/cell/     — Cell collaboration & governance tools
  - tools/advanced/ — Ring 2.5-3 write/destructive tools
  - tools/special/  — Composite, archive, L3 tools
Third-party plugins can call register_plugin() to add their own tools.
"""

from .tool_spec import auto_discover, register_plugin, register, ToolSpec, ParamSpec, TOOL_REGISTRY

# Auto-discover from all four tools/ subdirectories
import os as _os
_services_dir = _os.path.dirname(_os.path.abspath(__file__))
_src_root = _os.path.dirname(_services_dir)
_tool_base = _os.path.join(_src_root, "tools", "base")
_tool_cell = _os.path.join(_src_root, "tools", "cell")
_tool_advanced = _os.path.join(_src_root, "tools", "advanced")
_tool_special = _os.path.join(_src_root, "tools", "special")

_total = 0
for _d in (_tool_base, _tool_cell, _tool_advanced, _tool_special):
    _total += auto_discover(_d)
print(f"[tool_registry] auto-discovered {_total} modules from 4 tool dirs → {len(TOOL_REGISTRY)} tools")