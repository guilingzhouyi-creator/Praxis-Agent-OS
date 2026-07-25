"""LLM base types — provider abstract base, data types, tool search.

Extracted from llm.py to separate concerns:
  - Provider ABC + registry
  - Data types (LLMConfig, ToolDef, ToolCall, ToolResult)
  - ToolSearch (deferred tool loading)
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

from kernel.params import DEFAULT_REASONING_EFFORT, DEFAULT_THINKING_BUDGET

logger = logging.getLogger(__name__)


# ── Provider ABC ──

class LLMProvider(ABC):
    """Abstract base for all LLM providers.

    Subclasses MUST implement generate() and may override name.
    Register with register_provider() for discovery.
    """
    name: str = ""

    @abstractmethod
    def generate(self, prompt: str, system: str = "",
                 max_tokens: int = 512, user_id: str = "",
                 **kwargs) -> dict:
        """Generate a response from the LLM. Must be implemented by subclasses."""


_PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {}


def register_provider(name: str, provider_cls: type[LLMProvider],
                      override: bool = False) -> None:
    """Register an LLM provider for discovery via config."""
    if name in _PROVIDER_REGISTRY and not override:
        raise ValueError(f"provider '{name}' already registered")
    _PROVIDER_REGISTRY[name] = provider_cls


def list_providers() -> list[str]:
    return sorted(_PROVIDER_REGISTRY.keys())


# ── Data types ──

@dataclass
class LLMConfig:
    provider: str = "mock"
    model: str = ""
    max_tokens: int = 2048
    temperature: float = 0.3
    api_key: str = ""
    api_url: str = ""
    device_name: str = "llm"
    cache_breakpoints: int = 4
    cache_retention: float = 86400.0
    tool_search: bool = False
    use_websocket: bool = False
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    thinking_budget: int = DEFAULT_THINKING_BUDGET

    def __eq__(self, other):
        if not isinstance(other, LLMConfig):
            return False
        return (self.provider == other.provider and self.model == other.model
                and self.api_url == other.api_url)


@dataclass
class ToolDef:
    """Tool definition for LLM function calling (deprecated, use ToolSpec).

    ToolSpec in tool_spec.py is the canonical tool definition.
    ToolDef remains for backward compatibility.
    """
    name: str
    description: str
    parameters: dict
    handler: Callable | None = None
    parallel_safe: bool = False  # True = read-only, can run concurrently


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""
    name: str
    arguments: dict
    call_id: str = ""


@dataclass
class ToolResult:
    """Result of executing a tool call."""
    name: str
    result: dict
    call_id: str = ""
    error: str = ""


# ── Tool Search (deferred tool loading) ──

class ToolSearch:
    """Deferred tool loading — only send relevant tool definitions to LLM."""

    def __init__(self, max_tools: int = 20):
        self._tools: dict[str, Any] = {}
        self._max_tools = max_tools

    def register(self, tool: Any) -> None:
        self._tools[tool.name] = tool

    def register_many(self, tools: list[Any]) -> None:
        for t in tools:
            self._tools[t.name] = t

    def search(self, query: str, max_results: int = 10) -> list[Any]:
        if not query or not self._tools:
            return list(self._tools.values())[:max_results]
        query_lower = query.lower()
        scored = []
        for name, tool in self._tools.items():
            score = 0
            if query_lower in name.lower():
                score += 3
            if query_lower in tool.description.lower():
                score += 2
            params_str = json.dumps(tool.parameters).lower()
            if query_lower in params_str:
                score += 1
            scored.append((score, name, tool))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [t for _, _, t in scored[:max_results]]

    def to_api_format(self, tools: list[ToolDef] | None = None) -> list[dict]:
        if tools is None:
            tools = list(self._tools.values())[:self._max_tools]
        return [
            t.to_api_format() if hasattr(t, 'to_api_format')
            else {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
            }
            for t in tools
        ]

    def count(self) -> int:
        return len(self._tools)
