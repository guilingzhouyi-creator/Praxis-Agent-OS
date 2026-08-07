"""Tool parameter types — extracted from tool_spec.py for modularity.

Contains ParamSpec and ReturnSpec dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParamSpec:
    """Tool parameter specification."""

    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    description: str = ""

    def validate(self, value: Any) -> str | None:
        """Validate a value against this param spec; returns an error string or None."""
        if value is None and not self.required:
            return None
        type_map = {"string": str, "int": int, "bool": bool, "list": list, "dict": dict}
        expected = type_map.get(self.type)
        if expected and value is not None and not isinstance(value, expected):
            return f"{self.name}: expected {self.type}, got {type(value).__name__}"
        return None


@dataclass
class ReturnSpec:
    """Tool return value specification."""

    type: str = "object"
    description: str = ""
    properties: dict[str, str] = field(
        default_factory=lambda: {
            "success": "bool",
            "data": "any",
            "error": "string?",
        }
    )
