"""Boot initialization — service init, config load, device registration.
Extracted from boot.py for modularity.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def init_services() -> dict:
    """Initialize all kernel services and mount default VFS paths."""
    from kernel import get_event_bus
    from kernel.constitution import get_constitution
    from kernel.allocator import get_allocator
    from kernel.gatechain import get_gatechain
    from kernel.swapper import get_swapper
    from kernel.vfs import get_vfs, MountType

    init_order = [
        ("constitution", get_constitution),
        ("event_bus", get_event_bus),
        ("allocator", get_allocator),
        ("gatechain", get_gatechain),
        ("swapper", lambda: get_swapper(interval=60.0)),
    ]
    results = {}
    for name, fn in init_order:
        try:
            fn()
            results[name] = "ok"
        except Exception as e:
            results[name] = f"error: {e}"

    vfs = get_vfs()
    vfs.mount("/project", MountType.PROJECT, min_ring=1, read_only=False, description="Project root")
    vfs.mount("/proc", MountType.SYSTEM, min_ring=1, read_only=True, description="Kernel process table")
    vfs.mount("/tmp", MountType.TEMP, min_ring=1, read_only=False, description="Temporary files")

    from .config_loader import load_and_apply as _apply_cfg
    cfg_r = _apply_cfg()
    if cfg_r.get("success"):
        logger.info("config loaded: %s", cfg_r.get("applied", {}))
    else:
        logger.info("no config file, using defaults")

    try:
        from .config_loader import load as load_config
        raw = load_config()
        if raw:
            from .settings_center import get_center
            get_center().load_l2(raw)
    except Exception as e:
        logger.warning("boot: %s", e)

    from kernel.device import get_device_manager, DeviceType
    dm = get_device_manager()
    dm.register("llm", DeviceType.LLM, rate_limit=10, description="Default LLM backend")
    dm.register("filesystem", DeviceType.STORAGE, rate_limit=100, description="Local filesystem")
    dm.start_health_checks()

    vfs.mount("/sys", MountType.VIRTUAL, min_ring=1, read_only=True, description="System registry")
    vfs.mount("/dev", MountType.VIRTUAL, min_ring=1, read_only=True, description="Device manager")
    vfs.mount("/skills", MountType.VIRTUAL, min_ring=1, read_only=True, description="Agent skills")

    from kernel.skill import get_skill_manager
    sm = get_skill_manager()
    n = sm.load_builtin()
    if n > 0:
        logger.info("loaded %d skills", n)

    try:
        from kernel.net import get_net
        get_net().start()
        results["network"] = "ok"
    except Exception as e:
        results["network"] = f"skip: {e}"

    try:
        from .htn_planner import get_service as get_htn
        get_htn()
        results["htn_planner"] = "ok"
    except Exception as e:
        results["htn_planner"] = f"error: {e}"

    from kernel.prompts import load_prompt_overrides
    from .settings_center import get_center
    all_s = get_center().all()
    prompt_cfg = {k.split("prompts.", 1)[1]: v for k, v in all_s.items() if k.startswith("prompts.")}
    if prompt_cfg:
        load_prompt_overrides(prompt_cfg)
        results["prompts"] = "ok"

    from kernel.params.system import KERNEL_VERSION
    results["version"] = KERNEL_VERSION

    # Start R4Agent background archive loop
    try:
        from .r4_agent import start_r4_agent
        start_r4_agent()
        results["r4_agent"] = "started"
    except Exception as e:
        results["r4_agent"] = f"error: {e}"

    return results
