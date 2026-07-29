"""Shell session state — tracks L3A/Direct mode, agent identity, and session ID."""

import threading

from l1.kernel.params.agent import DEFAULT_CELL_ID


class ShellState:
    """Singleton shell state — mode (L3A/Direct), connected agent, session ID."""

    def __init__(self):
        self._lock = threading.Lock()
        self.mode: str = "L3A"
        self.cell_id: str = DEFAULT_CELL_ID
        self.agent_id: str = ""
        self.session_id: str = ""
        self._preconnect_cache: dict = {}

    def is_direct(self) -> bool:
        """Check if shell is in Direct (connected-to-agent) mode."""
        with self._lock:
            return self.mode == "DIRECT" and bool(self.agent_id)

    def switch_to_direct(self, cell_id: str, agent_id: str,
                         session_id: str = "") -> None:
        """Switch shell to Direct mode, targeting a specific Cell/Agent."""
        with self._lock:
            self.mode = "DIRECT"
            self.cell_id = cell_id
            self.agent_id = agent_id
            self.session_id = session_id

    def switch_to_l3a(self) -> None:
        """Return shell to L3A (default) mode — disconnect current agent."""
        with self._lock:
            self.mode = "L3A"
            self.agent_id = ""
            self.session_id = ""


_shell_state = ShellState()


def get_state() -> ShellState:
    """Get the singleton ShellState instance."""
    return _shell_state


def reset_state() -> None:
    """Reset the shell state to defaults — clears mode, agent, and session."""
    global _shell_state
    _shell_state = ShellState()
