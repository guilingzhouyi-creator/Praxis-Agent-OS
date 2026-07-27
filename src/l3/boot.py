"""Boot sequence — Agent OS kernel startup and initialization, extensible via boot step registry.

Boot flow:
  1. Load constitution
  2. Initialize all kernel services
  3. Create Cell(s) with 3 Peer Agents
  4. Register agents with scheduler, IPC bus, ACB, identity
  5. Start heartbeat monitoring
  6. Start L3 coordinator
  7. Cell is ready to receive cards

Each Cell runs 3 Peer Agent terminals (A/B/C) + dynamic Scout pool.

Extending boot:
  from l3.boot import register_boot_step
  register_boot_step("my_step", my_fn, depends_on=["init_services"])
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from l1.kernel.params.agent import TERRITORY_PATHS, DEFAULT_AGENT_CONFIGS, DEFAULT_CELL_ID
from l1.kernel.params.api import LLM_RATE_LIMIT_DEFAULT, FILESYSTEM_RATE_LIMIT_DEFAULT
from l1.kernel.params.system import PERSIST_AUTO, PERSIST_INTERVAL, KERNEL_VERSION

logger = logging.getLogger(__name__)

_BOOT_STEPS: list[str] = []
_BOOT_STARTED: float = 0.0
_BOOT_RESULT: dict | None = None

# ── Boot step registry (extensible) ──

@dataclass
class BootStep:
    name: str = ""
    fn: Callable = lambda: {}
    depends_on: list[str] = field(default_factory=list)

_boot_registry: dict[str, BootStep] = {}
_boot_registry_locked: bool = False


def register_boot_step(name: str, fn: Callable,
                       depends_on: list[str] | None = None,
                       override: bool = False) -> None:
    """Register a boot step. Steps are ordered by dependency before execution.

    Args:
        name: Unique step name. Used as key in results dict.
        fn: Callable that returns a dict (at minimum {"success": True/False}).
        depends_on: List of step names that must complete first.
        override: If True, replace an existing step with the same name.
    """
    if _boot_registry_locked and not override:
        raise RuntimeError("boot registry is locked (already executed)")
    if name in _boot_registry and not override:
        raise ValueError(f"boot step '{name}' already registered; use override=True")
    _boot_registry[name] = BootStep(name=name, fn=fn, depends_on=depends_on or [])


def _resolve_boot_order() -> list[str]:
    """Topological sort of registered boot steps by dependency."""
    names = list(_boot_registry.keys())
    ordered = []
    visited = set()
    in_stack = set()

    def _dfs(n: str) -> bool:
        if n in in_stack:
            return False
        if n in visited:
            return True
        in_stack.add(n)
        step = _boot_registry.get(n)
        if step:
            for dep in step.depends_on:
                if dep in _boot_registry and not _dfs(dep):
                    return False
            ordered.append(n)
        in_stack.discard(n)
        visited.add(n)
        return True

    for n in names:
        if n not in visited:
            _dfs(n)
    return ordered


def _wire_kernel_os() -> None:
    """Register service-layer callbacks with the kernel OS so shutdown
    does NOT need to import from services/ directly."""
    try:
        from l1.kernel.os import get_os
        from .memory_init import shutdown_to_memories
        from .agent_terminal import reset_terminals
        from .cell import reset_cells
        osys = get_os()
        osys.register_shutdown_handler(shutdown_to_memories)
        osys.register_terminal_reset(reset_terminals)
        osys.register_cell_reset(reset_cells)
    except Exception as e:
        logger.warning("kernel OS wiring skipped: %s", e)


def boot(agent_config: list[tuple[str, str, list[str]]] | None = None,
         interactive: bool = True) -> dict:
    """Full kernel boot sequence.

    Args:
        agent_config: list of (agent_id, role, territory) tuples.
        interactive: If True, runs bootstrap wizard on first boot.
    """
    global _BOOT_STARTED, _BOOT_RESULT

    _wire_kernel_os()

    _BOOT_STARTED = time.time()
    _BOOT_STEPS.clear()

    # First-boot bootstrap wizard
    try:
        from .bootstrap import needs_bootstrap, run_bootstrap
        if needs_bootstrap():
            logger.info("first boot detected — running bootstrap wizard")
            br = run_bootstrap(interactive=interactive)
            _BOOT_STEPS.append("bootstrap")
            if not br.get("success"):
                logger.warning("bootstrap incomplete: %s", br.get("error", ""))
    except Exception as e:
        from l3.error_bus import capture
        capture("bootstrap check failed", exc=e, component="kernel")
        logger.warning("bootstrap check: %s", e)

    # Register shutdown handler (atexit + signal) so state is always saved
    try:
        from .memory_init import register_shutdown_handler
        register_shutdown_handler()
        _BOOT_STEPS.append("shutdown_handler")
    except Exception as e:
        from l3.error_bus import capture
        capture("shutdown handler failed", exc=e, component="kernel")
        logger.warning("boot shutdown handler: %s", e)

    # Restore previous state if available
    try:
        from l1.kernel.persist import restore
        r = restore()
        if r.get("success"):
            _BOOT_STEPS.append("restored")
            logger.info("restored kernel state: %s processes, %s devices",
                        r.get("processes", 0), r.get("devices", 0))
    except Exception as e:
        logger.warning("boot restore: %s", e)

    # Start auto-save background thread
    if PERSIST_AUTO:
        def _save_loop():
            while True:
                time.sleep(PERSIST_INTERVAL)
                try:
                    from l1.kernel.persist import save
                    save()
                except Exception as e:
                    logger.warning("auto-save failed: %s", e)
        t = threading.Thread(target=_save_loop, daemon=True, name="persist")
        t.start()
        logger.info("auto-save started (every %.0fs)", PERSIST_INTERVAL)

    # Try to load agent config from memories first
    if agent_config is None:
        try:
            from .memory_init import init_from_memories
            m = init_from_memories()
            if m.get("loaded"):
                agent_config = m["agent_config"]
                _BOOT_STEPS.append("snapshot_restore")
                logger.info("boot from memories: %d agents from %s",
                            len(agent_config), m.get("source", "?"))
        except Exception as e:
            logger.warning("memory init skipped: %s", e)

    if agent_config is None:
        # Generate agent config from territory paths (roles from constitution)
        agent_config = [
            (role, role, list(paths))
            for role, paths in TERRITORY_PATHS.items()
        ][:3]

    # Reset locked flag so re-boot after failure is possible
    global _boot_registry_locked
    _boot_registry_locked = False
    _boot_registry.clear()
    # Register built-in boot steps
    _register_default_boot_steps(agent_config)
    _boot_registry_locked = True

    order = _resolve_boot_order()
    results = {}
    success = True

    for name in order:
        step = _boot_registry.get(name)
        if not step:
            continue
        try:
            r = step.fn()
            results[name] = r
            _BOOT_STEPS.append(name)
            if not r.get("success", True):
                logger.error("boot step failed: %s — %s", name, r.get("error", ""))
                success = False
                break
        except Exception as e:
            from l3.error_bus import capture
            capture(f"boot step {name} failed", exc=e, component="kernel")
            results[name] = {"success": False, "error": str(e)}
            success = False
            break

    elapsed = time.time() - _BOOT_STARTED
    cell_result = results.get("create_cell", {})
    _BOOT_RESULT = {
        "success": success,
        "elapsed": round(elapsed, 3),
        "steps": list(_BOOT_STEPS),
        "results": results,
        "agent_count": len(agent_config),
        "cell_id": cell_result.get("cell_id", "cell-1"),
        "agents": cell_result.get("agents", []),
    }
    # Save boot snapshot to memories so next restart knows what was running
    if success and agent_config:
        try:
            from .memory_init import save_boot_snapshot
            path = save_boot_snapshot(agent_config)
            if path:
                _BOOT_RESULT["snapshot"] = path
        except Exception as e:
            logger.warning("boot snapshot save failed: %s", e)
    logger.info("boot %s in %.2fs: %s", "OK" if success else "FAILED", elapsed, _BOOT_STEPS)
    return _BOOT_RESULT


def _register_default_boot_steps(agent_config: list | None) -> None:
    """Register all built-in boot steps via the extensible registry."""
    register_boot_step("load_constitution", _load_constitution, depends_on=[])
    register_boot_step("load_config", _load_config, depends_on=["load_constitution"])
    register_boot_step("load_tools", _load_tools, depends_on=["load_config"])
    register_boot_step("init_system_bus", _init_system_bus, depends_on=["load_tools"])
    register_boot_step("init_services", _init_services, depends_on=["init_system_bus"])
    register_boot_step("init_record_center", _init_record_center,
                       depends_on=["init_services"])
    register_boot_step("create_cell", lambda: _create_cell(agent_config),
                       depends_on=["init_record_center"])


def _load_constitution() -> dict:
    """Load constitution from .nomos-rules.md into both territory and rule engine."""
    from pathlib import Path
    from l1.kernel.params.agent import CONSTITUTION_ENV_VAR
    from l1.kernel.paths import get_paths
    from l1.kernel.constitution import load_territory, TerritoryConstitution, get_constitution
    constitution_path = get_paths().constitution_file
    path = Path(os.environ.get(CONSTITUTION_ENV_VAR, constitution_path))
    try:
        if path.exists():
            c = load_territory(str(path))
            if not c or not isinstance(c, TerritoryConstitution):
                return {"success": True, "source": str(path), "assembly_mode": True}
            engine_load = get_constitution().load(str(path))
            if not engine_load.get("success"):
                logger.warning("constitution engine load failed: %s", engine_load.get("error", ""))
            return {
                "success": True, "source": str(path),
                "assembly_mode": False,
                "rules": engine_load.get("rules", 0),
            }
        return {"success": True, "source": "none", "assembly_mode": True}
    except Exception as e:
        logger.error("constitution load error: %s", e)
        return {"success": False, "error": str(e), "assembly_mode": True}


def _load_config() -> dict:
    """Load praxis.yaml config and apply to system settings.

    Returns success=True even on config-not-found so first-boot is not blocked,
    but adds ``_non_fatal`` flag so boot reporting can distinguish."""
    try:
        from .config_loader import load_and_apply
        r = load_and_apply()
        if r.get("success"):
            return {"success": True, "applied": r.get("applied", {})}
        return {"success": True, "_non_fatal": True, "note": r.get("error", "config load failed")}
    except Exception as e:
        logger.error("config load error: %s", e)
        return {"success": True, "_non_fatal": True, "note": str(e)}


def _init_kernel_and_vfs() -> dict:
    """Init kernel core services + VFS + config + devices."""
    from l1.kernel import get_event_bus
    from l1.kernel.constitution import get_constitution
    from l1.kernel.allocator import get_allocator
    from l1.kernel.swapper import get_swapper
    from l1.kernel.gatechain import get_gatechain
    from l1.kernel.vfs import get_vfs, MountType
    from l1.kernel.device import get_device_manager, DeviceType
    from l1.kernel.params.system import KERNEL_VERSION

    results = {}
    for name, fn in [
        ("constitution", get_constitution), ("event_bus", get_event_bus),
        ("allocator", get_allocator), ("gatechain", get_gatechain),
        ("swapper", lambda: get_swapper(interval=60.0)),
    ]:
        try:
            fn(); results[name] = "ok"
        except Exception as e:
            results[name] = f"error: {e}"

    vfs = get_vfs()
    for path, mtype, ro in [("/project", MountType.PROJECT, False),
                             ("/proc", MountType.SYSTEM, True),
                             ("/tmp", MountType.TEMP, False)]:
        vfs.mount(path, mtype, min_ring=1, read_only=ro, description=path.strip("/"))
    for path, mtype, ro in [("/sys", MountType.VIRTUAL, True),
                             ("/dev", MountType.VIRTUAL, True),
                             ("/skills", MountType.VIRTUAL, True)]:
        vfs.mount(path, mtype, min_ring=1, read_only=ro, description=path.strip("/"))

    from .config_loader import load_and_apply as _apply_cfg
    r = _apply_cfg()
    logger.info("config: %s", r.get("applied", {}) if r.get("success") else "defaults")
    try:
        raw = r.get("applied", {})
        if raw:
            from .settings_center import get_center
            get_center().load_l2(raw)
    except Exception as e:
        logger.warning("boot config: %s", e)

    dm = get_device_manager()
    dm.register("llm", DeviceType.LLM, rate_limit=LLM_RATE_LIMIT_DEFAULT, version=KERNEL_VERSION)
    dm.register("filesystem", DeviceType.STORAGE, rate_limit=FILESYSTEM_RATE_LIMIT_DEFAULT, version=KERNEL_VERSION)
    dm.start_health_checks()
    return results


def _load_tools() -> dict:
    """Load tool definitions from tools.yaml into TOOL_REGISTRY."""
    try:
        from .tool_config import ToolConfig
        n = ToolConfig.load()
        return {"success": True, "tools": n}
    except Exception as e:
        logger.warning("tool_config load failed: %s", e)
        return {"success": False, "error": str(e)}


def _init_record_center() -> dict:
    """Init RecordCenter and bridge to StatsCenter."""
    try:
        from .record_center import get_record_center
        rc = get_record_center()
        rc.bridge_stats()
        logger.info("record_center: initialized, export_dir=%s", rc._export_dir)
        return {"success": True}
    except Exception as e:
        logger.warning("record_center init: %s", e)
        return {"success": False, "error": str(e)}


def _init_skills_and_network() -> dict:
    """Init skills, network kernel, HTN planner."""
    results = {}
    from l1.kernel.skill import get_skill_manager
    n = get_skill_manager().load_builtin()
    if n > 0: logger.info("loaded %d skills", n)
    try:
        from l1.kernel.net import get_net; get_net().start(); results["network"] = "ok"
    except Exception as e: results["network"] = f"skip: {e}"
    try:
        from .htn_planner import get_service as get_htn; get_htn(); results["htn_planner"] = "ok"
    except Exception as e: results["htn_planner"] = f"error: {e}"
    return results


def _init_memory_and_archive() -> dict:
    """Init MemoryManager, Archive, R4Agent, IssueTable, CredentialVault."""
    results = {}
    try:
        from .memory import get_memory; mem = get_memory()
        mem.set_persist_dir("memories")
        mr = mem.restore(); results["memory_restore"] = f"{mr.get('restored',0)} entries"
        # Wire swapper to memory service
        try:
            from l1.kernel.swapper import get_swapper
            swp = get_swapper()
            swp.set_memory(mem)
            results["swapper_wired"] = "ok"
        except Exception as e:
            results["swapper_wired"] = f"skip: {e}"
    except Exception as e: results["memory_restore"] = f"skip: {e}"
    try:
        from tools._archive import init_archive
        init_archive(); results["archive_init"] = "ok"
    except Exception as e: results["archive_init"] = f"skip: {e}"
    try:
        from .archive_orchestrator import ring3_from_archive
        n = ring3_from_archive(get_memory())
        results["archive_restore"] = f"{n} entries"
    except Exception as e: results["archive_restore"] = f"skip: {e}"
    try:
        from .r4_agent import start_r4_agent; start_r4_agent(); results["r4_agent"] = "started"
    except Exception as e: results["r4_agent"] = f"error: {e}"
    for mod, name in [("issue", "get_table"),
                       ("cache_doc", "get_store"),
                       ("credential_vault", "init_vault"),
                       ("tool_mode", "init_tool_mode"),
                       ("central_security", "get_center"),
                       ("central_memory", "get_center"),
                       ("central_plugin", "get_center")]:
        try:
            import importlib
            m = importlib.import_module(f".{mod}", __package__)
            getattr(m, name)()
            results[mod] = "ok"
        except Exception as e:
            results[mod] = f"skip: {e}"
    return results


def _init_system_bus() -> dict:
    """Initialize SystemBus root with global service components.

    Registers EventBus, StatsCenter, RecordCenter, CentralController
    so they participate in the unified lifecycle and event routing.
    """
    results = {}
    try:
        from l1.kernel.bus import get_root_bus, SystemBus
        root = get_root_bus()

        # Mount sub-buses
        gs = root.mount("global")

        # Register global components
        from l3.global_components import (
            StatsCenterComponent, RecordCenterComponent,
            EventBusComponent, CentralControllerComponent,
        )
        gs.register(StatsCenterComponent())
        gs.register(RecordCenterComponent())
        gs.register(EventBusComponent())
        gs.register(CentralControllerComponent())

        # The Cell bus will be mounted by _create_cell later

        gs.install()
        results["system_bus"] = "ok"
        results["components"] = [c.meta.name for c in gs.list()]
    except Exception as e:
        logger.warning("system_bus init: %s", e)
        results["system_bus"] = f"skip: {e}"
    return results


def _init_services() -> dict:
    """Initialize all kernel services."""
    results = {}
    for sub_fn in [_init_kernel_and_vfs, _init_skills_and_network, _init_memory_and_archive]:
        try:
            r = sub_fn()
            results.update(r)
        except Exception as e:
            logger.error("boot sub-init failed: %s", e)
    # Initialize MonitorBus + MessageGate
    try:
        from .monitor_bus import get_bus
        get_bus()  # warm singleton
        results["monitor_bus"] = "ok"
    except Exception as e:
        logger.warning("monitor_bus init: %s", e)
    try:
        from .monitor_bus import MonitorEvent, get_bus as _mb
        _mb().emit(MonitorEvent(type="system.boot", source="boot", severity="info", message="System booted"))
    except Exception:
        pass
    # Initialize ResourceBuffer (crash recovery + background flush)
    try:
        from .resource_buffer.manager import get_manager
        get_manager()  # warm singleton, triggers recover()
        results["resource_buffer"] = "ok"
    except Exception as e:
        logger.warning("resource_buffer init: %s", e)

    # Install LogService logging bridge (catches all logger.* calls)
    try:
        from .log import get_service as _ls
        _ls().install_handler()
        results["log_handler"] = "ok"
    except Exception as e:
        logger.warning("log handler install: %s", e)
    return {"success": True, "services": list(results.keys()), "results": results}


def _create_cell(agent_config: list[tuple[str, str, list[str]]] | None = None) -> dict:
    """Create Cell with configured agents + Scout pool."""
    from .cell import get_cell
    from .scout import get_pool as get_scout_pool
    from l1.kernel import register_process
    from l1.kernel.vfs import get_vfs, MountType
    from .scheduler import get_time_scheduler
    from .fault_tolerance import get_service as get_ft

    cell = get_cell(DEFAULT_CELL_ID)
    get_ft().start()
    registered = []
    for agent_id, role, territory in agent_config or []:
        cell.add_agent(agent_id, role=role, territory=territory, auto_boot=True)
        pid = register_process(agent_id, role=role, ring=1)
        get_time_scheduler().register(agent_id, priority=AGENT_PRIORITY.get(role, 5))
        get_ft().heartbeat(agent_id)
        registered.append({"agent": agent_id, "pid": pid})
        for t in territory:
            get_vfs().mount(f"/{agent_id}/{t.lstrip('/')}", MountType.PROJECT,
                           min_ring=1, read_only=False)

    get_scout_pool()

    # Register Cell with CardRegistry dispatcher + PendingQueue callback
    try:
        from .card_registry import get_registry
        reg = get_registry()
        reg.register_cell(DEFAULT_CELL_ID, cell.territory)
        reg.set_cell_resolver(lambda cid: get_cell(cid) if cid == DEFAULT_CELL_ID else get_cell(cid))
        reg.start_dispatcher()
        # Wire PendingQueue approve → CardRegistry.restore_card
        from .pending_queue import get_queue
        pq = get_queue()
        pq.set_on_approve(lambda cid: reg.restore_card(cid))
    except Exception as e:
        logger.warning("card registry setup: %s", e)

    return {"success": True, "cell_id": DEFAULT_CELL_ID,
            "agents": [a[0] for a in agent_config] if agent_config else [],
            "registered": registered}


def _default_constitution() -> str:
    return """# NOMOS Constitution (default)
G1: workspace_fingerprint
G2: identity_verification
G3: permission_check
G4: compliance_scan
G5: report_decision
"""


def boot_status() -> dict:
    """Return boot status."""
    if _BOOT_RESULT:
        return _BOOT_RESULT
    return {"success": False, "error": "not booted", "steps": _BOOT_STEPS}


def boot_summary() -> str:
    """Return a human-readable boot summary."""
    if not _BOOT_RESULT:
        return "Kernel not booted."
    r = _BOOT_RESULT
    status = "OK" if r["success"] else "FAILED"
    return f"Boot {status} in {r['elapsed']}s — {len(r['steps'])} steps: {' → '.join(r['steps'])}"