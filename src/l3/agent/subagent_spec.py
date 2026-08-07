"""SubAgent specification definitions — built-in specs, lazy loading, YAML integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from l1.kernel.params.system import LOG_TRUNC_100

logger = logging.getLogger(__name__)


@dataclass
class SubAgentSpec:
    """Sub-agent spec definition."""
    name: str
    description: str
    system_prompt: str = ""
    allowed_tools: list[str] = field(default_factory=lambda: ["read_file", "grep_search"])
    model: str = ""
    max_steps: int = 5
    timeout: float = 60.0
    read_only: bool = True
    tags: list[str] = field(default_factory=list)
    model_spec: str = "subagent"            # model_spec reference name, defined in praxis.yaml
    model_config: dict | None = None        # per-spec model override dict
    strategy: str = ""                      # named model_spec strategy pack (fast/balanced/deep)
    sandbox_profile: str = ""          # empty=no sandbox, "safe"/"isolated"/"danger"
    post_actions: list[dict] = field(default_factory=list)
    """Post-execution actions chained after SubAgent completes.

    Each action dict:
      {"type": "scout", "prompt": "Verify the changes against conventions"}

    The SubAgent's result is injected as {result} in the scout prompt.
    Post-action results are merged into the final delivery.
    """

    def to_dict(self) -> dict:
        """Serialize the spec into a plain dict."""
        return {
            "name": self.name,
            "description": self.description[:LOG_TRUNC_100],
            "allowed_tools": self.allowed_tools,
            "model": self.model,
            "max_steps": self.max_steps,
            "timeout": self.timeout,
            "read_only": self.read_only,
            "tags": self.tags,
            "sandbox_profile": self.sandbox_profile,
            "model_spec": self.model_spec,
            "model_config": self.model_config,
            "strategy": self.strategy,
            "post_actions": self.post_actions,
        }


# ── Built-in subagent specs (loaded by SubAgentDispatcher) ──
# Config-driven via commands.yaml subagent_specs section.

_BUILTIN_SPECS: dict[str, dict] = {
    "security-auditor": {"description": "Security code review — scan for OWASP Top 10, hardcoded secrets, injection vectors",
        "system_prompt": "You are a senior security auditor. Review the provided code for vulnerabilities. "
                         "Check for: SQL injection, XSS, path traversal, hardcoded secrets, insecure crypto, "
                         "authorization bypasses. Rate each finding as CRITICAL/HIGH/MEDIUM/LOW.",
        "allowed_tools": ["read_file", "grep_search", "list_dir"],
        "max_steps": 8, "timeout": 120.0, "tags": ["security", "review"]},
    "code-reviewer": {"description": "General code review — logic errors, style, test coverage, edge cases",
        "system_prompt": "You are a senior engineer reviewing code. Check for: logic errors, "
                         "edge cases, style guide violations, missing error handling, "
                         "test coverage gaps, performance issues.",
        "allowed_tools": ["read_file", "grep_search", "list_dir"],
        "max_steps": 8, "timeout": 120.0, "tags": ["review"]},
    "documenter": {"description": "Generate documentation from code — docstrings, README, API reference",
        "system_prompt": "You are a technical writer. Read the code and generate documentation. "
                         "Focus on: public API surface, usage examples, edge cases, parameter descriptions.",
        "allowed_tools": ["read_file", "list_dir"],
        "max_steps": 6, "timeout": 90.0, "tags": ["docs"]},
    "data-analyst": {"description": "Analyze data files, logs, or structured output for patterns and anomalies",
        "system_prompt": "You are a data analyst. Read the provided data, identify patterns, "
                         "anomalies, and trends. Summarize findings with specific evidence.",
        "allowed_tools": ["read_file", "grep_search"],
        "max_steps": 6, "timeout": 90.0, "tags": ["data"]},
    "architect": {"description": "Architecture review — dependency analysis, module boundaries, design patterns",
        "system_prompt": "You are a software architect. Review the codebase structure. "
                         "Check for: circular dependencies, violation of layer boundaries, "
                         "missing abstractions, over-engineering, architectural drift.",
        "allowed_tools": ["read_file", "grep_search", "list_dir"],
        "max_steps": 10, "timeout": 180.0, "tags": ["architecture", "review"]},
    "helper": {"description": "General-purpose assistant — answer questions, explain code, suggest fixes",
        "system_prompt": "You are a helpful engineering assistant. Answer questions, explain code, "
                         "suggest fixes, and provide examples. Be concise and specific.",
        "allowed_tools": ["read_file", "grep_search", "list_dir"],
        "max_steps": 5, "timeout": 60.0, "read_only": False, "tags": ["general"]},
    "refactor-agent": {"description": "Refactor code — rename symbols, extract methods, split files, apply patterns",
        "system_prompt": "You are a senior software engineer performing code refactoring. "
                         "Read the target code, plan the refactoring steps, then execute them. "
                         "Ensure all tests still pass after each change.",
        "allowed_tools": ["read_file", "grep_search", "list_dir", "edit", "write_file"],
        "max_steps": 12, "timeout": 180.0, "read_only": False,
        "sandbox_profile": "safe", "tags": ["refactor", "write"],
        "post_actions": [{"type": "scout", "prompt": "Verify that the refactoring preserves behavior and all tests pass."}]},
    "fixer": {"description": "Fix bugs and issues — read error, locate cause, apply fix, verify",
        "system_prompt": "You are a debug technician. Read the error description, locate the root cause "
                         "in the codebase, apply the minimal fix, and verify the fix doesn't break tests. "
                         "Explain what caused the bug and how your fix resolves it.",
        "allowed_tools": ["read_file", "grep_search", "list_dir", "edit", "write_file", "shell"],
        "max_steps": 10, "timeout": 180.0, "read_only": False,
        "sandbox_profile": "safe", "tags": ["fix", "write"],
        "post_actions": [{"type": "scout", "prompt": "Verify that the fix resolves the issue without side effects."}]},
}


def load_specs() -> dict[str, SubAgentSpec]:
    """Load subagent specs from commands.yaml, falling back to built-in defaults.

    YAML section ``subagent_specs:`` overrides individual specs by name.
    Specs not present in YAML retain their built-in definitions.
    """
    import os

    import yaml
    specs: dict[str, SubAgentSpec] = {}

    # Start from built-in defaults
    for name, raw in _BUILTIN_SPECS.items():
        specs[name] = SubAgentSpec(name=name, **raw)

    # Apply YAML overrides
    from l1.kernel.params.system import COMMANDS_CONFIG_PATH
    yaml_path = os.path.join(os.getcwd(), COMMANDS_CONFIG_PATH)
    try:
        with open(yaml_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        yaml_specs = cfg.get("subagent_specs", {})
        for name, overrides in yaml_specs.items():
            if name in specs:
                # Merge: override individual fields, keep non-overridden fields from built-in
                for k, v in overrides.items():
                    if hasattr(specs[name], k):
                        setattr(specs[name], k, v)
            else:
                specs[name] = SubAgentSpec(name=name, **overrides)
    except Exception:
        logger.debug("subagent_spec: YAML override load failed")

    return specs


# Re-export for backward compat — lazy dict defers YAML loading until first access

class _LazyBuiltins(dict):
    """Dict subclass that loads specs on first access, not at import time.

    All dict operations (``__getitem__``, ``__iter__``, ``dict()``, etc.)
    trigger a single call to ``load_specs()`` on first use.
    """
    _loaded = False
    _data: dict[str, SubAgentSpec] = {}

    def _ensure(self) -> None:
        if not self._loaded:
            self._data = load_specs()
            self.__class__._loaded = True

    def __getitem__(self, key):
        self._ensure()
        return self._data[key]

    def __iter__(self):
        self._ensure()
        return iter(self._data)

    def __len__(self):
        self._ensure()
        return len(self._data)

    def __contains__(self, key):
        self._ensure()
        return key in self._data

    def keys(self):
        """Return the loaded spec keys, loading on first access."""
        self._ensure()
        return self._data.keys()

    def values(self):
        """Return the loaded spec values, loading on first access."""
        self._ensure()
        return self._data.values()

    def items(self):
        """Return the loaded spec items, loading on first access."""
        self._ensure()
        return self._data.items()

    def get(self, key, default=None):
        """Return the spec for *key* or *default*, loading on first access."""
        self._ensure()
        return self._data.get(key, default)

    def copy(self):
        """Return a plain dict copy of the loaded specs."""
        self._ensure()
        return dict(self._data)


BUILTIN_SUBAGENTS: dict[str, SubAgentSpec] = _LazyBuiltins()
