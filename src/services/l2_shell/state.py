"""Shell session state."""

from kernel.params.agent import DEFAULT_CELL_ID


class ShellState:
    def __init__(self):
        self.mode: str = "L3A"
        self.cell_id: str = DEFAULT_CELL_ID
        self.agent_id: str = ""
        self.session_id: str = ""
        self._preconnect_cache: dict = {}

    def is_direct(self) -> bool:
        return self.mode == "DIRECT" and bool(self.agent_id)

    def switch_to_direct(self, cell_id: str, agent_id: str,
                         session_id: str = "") -> None:
        self.mode = "DIRECT"
        self.cell_id = cell_id
        self.agent_id = agent_id
        self.session_id = session_id

    def switch_to_l3a(self) -> None:
        self.mode = "L3A"
        self.agent_id = ""
        self.session_id = ""


_shell_state = ShellState()


def get_state() -> ShellState:
    return _shell_state


def reset_state() -> None:
    global _shell_state
    _shell_state = ShellState()
