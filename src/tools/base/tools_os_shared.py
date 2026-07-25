"""OS tool shared functions - referenced by tools_os.py and tools.py."""

from constants import TOOL_DANGER_LEVEL


def get_tool_danger(tool_name: str) -> int:
    """Query tool danger level."""
    return TOOL_DANGER_LEVEL.get(tool_name, 0)