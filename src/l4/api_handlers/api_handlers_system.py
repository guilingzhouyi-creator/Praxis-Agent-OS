"""API handler mixin — system, lifecycle, settings, bootstrap handlers.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py`` (imported with a ``_`` alias and delegated).
"""

from __future__ import annotations

from typing import Any


def system_health(body: dict | None = None) -> dict:
    """Health probe — kernel self-test result."""
    try:
        from l1.kernel import health as _health_fn

        return _health_fn()
    except Exception as e:
        return {"status": "FAIL", "error": str(e)}


def list_processes(body: dict | None = None) -> dict:
    """List kernel process table."""
    try:
        from l1.kernel.process import get_table

        return {"processes": get_table().list_processes()}
    except Exception as e:
        return {"error": str(e)}


def list_devices(body: dict | None = None) -> dict:
    """List registered devices."""
    try:
        from l1.kernel.device import get_device_manager

        return {"devices": get_device_manager().list()}
    except Exception as e:
        return {"error": str(e)}


def settings_all(body: dict | None = None) -> dict:
    """Read all runtime settings."""
    try:
        from l3.config.settings_center import get_center

        return {"settings": get_center().all()}
    except Exception as e:
        return {"error": str(e)}


def settings_set_many(body: dict) -> dict:
    """Apply multiple settings at once."""
    try:
        from l3.config.settings_center import get_center

        return get_center().set_many(body)
    except Exception as e:
        return {"error": str(e)}


def list_syscalls(body: dict | None = None) -> dict:
    """List registered syscalls."""
    try:
        from l1.kernel.registry import get_registry

        return {"syscalls": get_registry().syscalls()}
    except Exception as e:
        return {"error": str(e)}


def bootstrap_status(body: dict | None = None) -> dict:
    """Whether a first-boot bootstrap is needed."""
    try:
        from l3.config.bootstrap import _CONFIG_PATH, needs_bootstrap

        return {"needed": needs_bootstrap(), "config_path": _CONFIG_PATH}
    except Exception as e:
        return {"error": str(e)}


def bootstrap_defaults(body: dict | None = None) -> dict:
    """Return default bootstrap configuration."""
    try:
        from l3.config.bootstrap import get_defaults

        return get_defaults()
    except Exception as e:
        return {"error": str(e)}


def bootstrap_apply(body: dict) -> dict:
    """Apply a bootstrap configuration payload."""
    try:
        from l3.config.bootstrap import apply_config

        return apply_config(body)
    except Exception as e:
        return {"error": str(e)}


def system_boot(body: dict | None = None) -> dict:
    """Boot kernel + Cell and summarize the result."""
    try:
        from l3.boot.boot import boot

        r = boot()
        return {
            "success": r.get("success", False),
            "elapsed": r.get("elapsed", 0),
            "agents": r.get("agents", []),
            "steps": r.get("steps", []),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def system_shutdown(body: dict | None = None) -> dict:
    """Shut the OS down."""
    try:
        from l1.kernel.os import get_os

        osys = get_os()
        return osys.shutdown()
    except Exception as e:
        return {"success": False, "error": str(e)}


def system_reboot(body: dict | None = None) -> dict:
    """Restart the OS."""
    try:
        from l1.kernel.os import get_os

        osys = get_os()
        r = osys.restart()
        return {"success": r.get("success", False), "elapsed": r.get("elapsed", 0)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def system_reload(body: dict | None = None) -> dict:
    """Reload constitution, config and tools."""
    try:
        from l3.boot.boot import _load_config, _load_constitution, _load_tools

        results = {}
        for name, fn in [("constitution", _load_constitution), ("config", _load_config), ("tools", _load_tools)]:
            try:
                r = fn()
                results[name] = "ok" if r.get("success") else r.get("error", "?")
            except Exception as e:
                results[name] = f"error: {e}"
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}


def system_reset(body: dict | None = None) -> dict:
    """Factory reset — optionally wipe configuration."""
    try:
        from l3.boot.lifecycle import factory_reset

        wipe_config = (body or {}).get("wipe_config", False)
        return factory_reset(wipe_config=wipe_config)
    except Exception as e:
        return {"success": False, "error": str(e)}


def system_boot_status(body: dict | None = None) -> dict:
    """Boot status merged with OS status."""
    try:
        from l1.kernel.os import get_os

        osys = get_os()
        from l3.boot.boot import boot_status

        r = boot_status()
        r["os"] = osys.status()
        return r
    except Exception as e:
        return {"error": str(e)}


def retriever_backend_get(body: dict | None = None) -> dict:
    """Skill retriever backend status."""
    from l3.memory.skill_retriever import retriever_status

    return retriever_status()


def retriever_backend_set(body: dict) -> dict:
    """Switch skill retriever backend."""
    from l3.memory.skill_retriever import set_backend

    return set_backend(body.get("backend", ""))


def _export_schema(body: dict | None = None) -> dict:
    """Unused placeholder kept for import symmetry with legacy exports."""
    return {"success": True}


_ = Any  # keep Any imported for signature annotations in re-exports
