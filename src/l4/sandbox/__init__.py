"""PolicySandbox — sandboxed execution layer for tool calls."""

from l4.sandbox.cell_sandbox import (
    CellSandbox,
    SandboxManager,
    SandboxEntry,
    get_manager,
    reset_manager,
    get_color_scheme,
    set_color_scheme,
    reset_color_scheme,
)
