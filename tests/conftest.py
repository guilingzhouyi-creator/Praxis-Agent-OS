"""pytest conftest — singleton reset between tests to avoid state pollution."""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

# ── xdist worker isolation ──
# Each parallel worker gets its own skill dir so parallel runs never contend
# on shared skill files. PRAXIS_DATA_DIR/PRAXIS_CONFIG_DIR are deliberately
# NOT overridden — tests like test_paths.py assert the default data_dir
# (".praxis") / config_file ("config/praxis.yaml") semantics, and those
# defaults must stay intact under xdist.
if os.environ.get("PYTEST_XDIST_WORKER"):
    _iso_dir = tempfile.mkdtemp(prefix="praxis-test-worker-")
    os.environ.setdefault("PRAXIS_SKILL_DIR", _iso_dir)

# Modules with singleton _xxx = None pattern that can pollute across tests
_RESETS = {
    "l4.api.api_gateway": ("stop_api", None),
    "l3.card.approval_gate": ("reset_gate", None),
    "l3.card.card_registry": ("reset_registry", None),
    "l3.card.issue": ("reset_table", None),
    "l3.memory.memory": ("reset_memory", None),
    "l3.memory.memory_graph": ("reset_graph", None),
    "l3.memory.memory_mer": ("reset_mer", None),
    "l3.config.settings_center": ("reset_center", None),
    "l3.tool_system.tool_registry": ("clear_mutes", None),
    "l3.memory.r4_agent": ("stop_r4_agent", None),
    "l3.agent.scout": ("reset_pool", None),
    "l3.scheduler.scheduler": ("reset_scheduler", None),
    "l3.scheduler.scheduler_time": ("reset_time_scheduler", None),
    "l3.scheduler.scheduler_rate": ("reset_rate_scheduler", None),
    "l3.scheduler.scheduler_scope": ("reset_scope_scheduler", None),
    "l3.agent_terminal": ("reset_terminals", None),
    "l3.cell": ("reset_cells", None),
    "l3.error_bus": ("reset_bus", None),
    "l1.kernel.event": ("reset_bus", None),
    "l4.lsp.lsp_manager": ("reset_manager", None),
    "l1.kernel.reputation": ("reset_reputation", None),
    "l1.kernel.sync": ("reset_registry", None),
    "l1.kernel.vfs": ("reset_vfs", None),
    "l3.boot.boot": ("reset_boot_state", None),
    "l3.boot.boot_registry": ("reset_registry", None),
    "l1.kernel.settings": ("reset_settings", None),
    "l1.kernel.errors": ("reset_error_capture_handler", None),
}


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset known singletons before each test to prevent state pollution.

    Lazy per-module: only modules already imported (``sys.modules``) are
    reset — a module the test suite never touched has no singleton to
    clean, so we skip its import cost instead of force-importing all 27.
    """
    errors = []
    for module_name, (func_name, _) in _RESETS.items():
        if module_name not in sys.modules:
            continue  # never imported → no singleton to reset
        try:
            mod = sys.modules[module_name]
            fn = getattr(mod, func_name, None)
            if fn:
                fn()
        except Exception as e:
            errors.append(f"{module_name}.{func_name}: {e}")
    # Command registry: after reset, reload default command defs + L2 shell
    # handlers so `/help` etc. stay registered across the full test run.
    # Only reload when the commands package was actually imported — an
    # unconditional importlib.reload() re-imports the whole L2 command tree
    # (pulling L3 modules) on every test, adding ~5s of setup cost.
    if "l2.l2_shell.commands" in sys.modules or "l1.kernel.commands" in sys.modules:
        try:
            from l1.kernel.commands import get_registry, load_command_defs, reset_registry
            reset_registry()
            get_registry()
            load_command_defs()
            import importlib

            import l2.l2_shell.commands as _cmds_mod
            importlib.reload(_cmds_mod)
        except Exception as e:
            errors.append(f"commands.reload: {e}")
    if errors:
        import logging
        logging.getLogger(__name__).debug("singleton resets: %s", errors)


# ── Shared fixtures for Cell / IRQ / PMU tests ──


class _FakePmu:
    """Mock PMU for tests — tracks increment calls."""
    def __init__(self):
        self.counts = {}

    def increment(self, name: str, delta: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + delta


@pytest.fixture
def fake_pmu():
    """Shared FakePmu instance for use across component tests."""
    return _FakePmu()


@pytest.fixture
def irq_controller(fake_pmu):
    """Fresh InterruptController wired to fake_pmu."""
    from l3.cell.components.cell_interrupt import InterruptController
    ctrl = InterruptController(cell_id="test-cell", pmu=fake_pmu)
    return ctrl


@pytest.fixture
def empty_cell():
    """Minimal Cell instance for component integration tests."""
    from l3.cell import Cell
    cell = Cell(cell_id="test-cell", territory=["."])
    return cell


@pytest.fixture
def cell_with_agents(empty_cell):
    """Cell with reader + writer agents pre-registered."""
    empty_cell.add_agent("agent-reader", role="reader", territory=["src/", "docs/"], ring=1)
    empty_cell.add_agent("agent-writer", role="writer", territory=["src/"], ring=2)
    return empty_cell


@pytest.fixture
def memory_manager():
    """MemoryManager instance for cross-Cell memory tests."""
    from l3.memory.memory import get_memory
    mm = get_memory()
    yield mm
    try:
        from l3.memory.memory import reset_memory
        reset_memory()
    except Exception:
        pass


@pytest.fixture
def terminal():
    """AgentTerminal instance for agent dispatch tests."""
    from l3.agent_terminal import get_terminal
    term = get_terminal("test-agent", role="reader", territory=["."])
    return term
