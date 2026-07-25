"""System settings — thin proxy over services.settings_adapter.

This module bridges kernel-space callers to the settings service.
Uses lazy imports to avoid import-time circular dependencies
while preserving the ``from kernel.settings import get_settings`` API.

The authoritative ``Settings`` instance lives in ``services/settings_adapter.py``.
Callers that can import from services directly should prefer that path.
"""

from __future__ import annotations

from typing import Any

# Re-export legacy DEFAULTS for callers that reference kernel.settings.DEFAULTS
DEFAULTS: dict[str, Any] = {
    "kernel.allocator.tokens": 4096,
    "kernel.allocator.ring1": 32,
    "kernel.allocator.ring2": 200,
    "kernel.swapper.interval": 30.0,
    "kernel.syscall.audit_max": 5000,
    "cell.terminal.workers": 4,
    "cell.terminal.poll": 0.05,
    "cell.card.timeout": 30.0,
    "llm.provider": "mock",
    "llm.model": "<model>",
    "llm.max_tokens": 2048,
    "llm.temperature": 0.3,
    "llm.rate_limit": 10,
    "device.rate_limit_default": 10,
    "device.health_check_interval": 60.0,
    "persist.enabled": True,
    "persist.interval": 30.0,
}


def get_settings():
    """Get the global Settings instance (delegates to services.settings_adapter)."""
    from services.settings_adapter import get_settings as _get
    return _get()


def reset_settings():
    """Reset the global Settings instance."""
    from services.settings_adapter import reset_settings as _reset
    _reset()
