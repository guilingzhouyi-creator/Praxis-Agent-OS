"""System settings — thin proxy over services.settings_adapter.

This module bridges kernel-space callers to the settings service.
Uses lazy imports to avoid import-time circular dependencies
while preserving the ``from l1.kernel.settings import get_settings`` API.

The authoritative ``Settings`` instance lives in ``services/settings_adapter.py``.
Callers that can import from services directly should prefer that path.
"""

from __future__ import annotations

from typing import Any

from l1.kernel.params.api import DEFAULT_MODEL_OLLAMA_CODER

# Re-export legacy DEFAULTS for callers that reference kernel.settings.DEFAULTS
DEFAULTS: dict[str, Any] = {
    "l1.kernel.allocator.tokens": 4096,
    "l1.kernel.allocator.ring1": 32,
    "l1.kernel.allocator.ring2": 200,
    "l1.kernel.swapper.interval": 30.0,
    "l1.kernel.syscall.audit_max": 5000,
    "cell.terminal.workers": 4,
    "cell.terminal.poll": 0.05,
    "cell.card.timeout": 30.0,
    "llm.provider": "ollama",
    "llm.model": DEFAULT_MODEL_OLLAMA_CODER,
    "llm.max_tokens": 2048,
    "llm.temperature": 0.3,
    "llm.rate_limit": 10,
    "device.rate_limit_default": 10,
    "device.health_check_interval": 60.0,
    "persist.enabled": True,
    "persist.interval": 30.0,
    "memory.graph.enabled": False,
    "memory.mer.enabled": False,
    "user_profile.enabled": False,
    # System-prompt injection switches (user-configurable via SettingsCenter API).
    # Each domain gates a block appended to agent system prompts; default True
    # keeps current behavior, set False to strip that injection globally.
    "prompt.inject.profile": True,
    "prompt.inject.constitution": True,
    "prompt.inject.skills": True,
    "prompt.inject.verification": True,
    "prompt.inject.memory": True,
    # CI review (card-triggered automation) — mirrors praxis.yaml `ci:` section.
    "ci.review.enabled": True,
    "ci.review.auto_trigger": True,
    "ci.review.llm_review": False,
    "ci.review.escalate_reject": False,
    "ci.review.route_convention": False,
    "ci.review.reputation": False,
    "ci.review.lean_trace": False,
    "ci.review.todo_linkage": False,
    "ci.review.consume_auto_test_cache": True,
    "ci.review.notify.enabled": False,
    # CI review control-plane permissions (per-surface write gates; not
    # modifiable via the business surfaces themselves — config/admin only).
    "ci.control.api.writable": True,
    "ci.control.shell.writable": True,
}


def inject_enabled(domain: str) -> bool:
    """Whether the ``prompt.inject.<domain>`` system-prompt injection is on.

    Best-effort: any settings failure falls back to enabled (True), so a
    broken settings path can never strip safety-critical context silently.
    """
    try:
        return bool(get_settings().get(f"prompt.inject.{domain}", True))
    except Exception:
        return True


def get_settings():
    """Get the global Settings instance (delegates to services.settings_adapter)."""
    from l3.config.settings_adapter import get_settings as _get
    return _get()


def reset_settings():
    """Reset the global Settings instance."""
    from l3.config.settings_adapter import reset_settings as _reset
    _reset()
