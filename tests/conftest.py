"""pytest conftest — singleton reset between tests to avoid state pollution."""
from __future__ import annotations

import pytest


# Modules with singleton _xxx = None pattern that can pollute across tests
_RESETS = {
    "services.api_gateway": ("stop_api", None),
    "services.approval_gate": ("reset_gate", None),
    "services.card_registry": ("reset_registry", None),
    "services.issue": ("reset_table", None),
    "services.memory": ("reset_memory", None),
    "services.settings_center": ("reset_center", None),
    "services.tool_spec": ("clear_mutes", None),
    "services.r4_agent": ("stop_r4_agent", None),
    "services.scout": ("reset_pool", None),
    "services.scheduler": ("reset_scheduler", None),
    "services.agent_terminal": ("reset_terminals", None),
    "services.cell": ("reset_cells", None),
    "services.error_bus": ("reset_bus", None),
    "services.lsp_manager": ("reset_manager", None),
    "services.file_editor": (None, None),
    "services.sse_bridge": (None, None),
}


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset all known singletons before each test to prevent state pollution."""
    errors = []
    for module_name, (func_name, _) in _RESETS.items():
        try:
            mod = __import__(module_name, fromlist=[func_name])
            fn = getattr(mod, func_name, None)
            if fn:
                fn()
        except Exception as e:
            errors.append(f"{module_name}.{func_name}: {e}")
    if errors:
        import logging
        logging.getLogger(__name__).debug("singleton resets: %s", errors)
