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
    "l1.kernel.event": ("reset_bus", None),
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
