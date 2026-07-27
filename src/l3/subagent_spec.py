from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

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
    sandbox_profile: str = ""          # empty=no sandbox, "safe"/"isolated"/"danger"
    post_actions: list[dict] = field(default_factory=list)
    """Post-execution actions chained after SubAgent completes.

    Each action dict:
      {"type": "scout", "prompt": "Verify the changes against conventions"}

    The SubAgent's result is injected as {result} in the scout prompt.
    Post-action results are merged into the final delivery.
    """

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description[:100],
            "allowed_tools": self.allowed_tools,
            "model": self.model,
            "max_steps": self.max_steps,
            "timeout": self.timeout,
            "read_only": self.read_only,
            "tags": self.tags,
            "sandbox_profile": self.sandbox_profile,
            "post_actions": self.post_actions,
        }


# ── Built-in subagent specs (loaded by SubAgentDispatcher) ──

BUILTIN_SUBAGENTS: dict[str, SubAgentSpec] = {
    "security-auditor": SubAgentSpec(
        name="security-auditor",
        description="Security code review — scan for OWASP Top 10, hardcoded secrets, injection vectors",
        system_prompt="You are a senior security auditor. Review the provided code for vulnerabilities. "
                      "Check for: SQL injection, XSS, path traversal, hardcoded secrets, insecure crypto, "
                      "authorization bypasses. Rate each finding as CRITICAL/HIGH/MEDIUM/LOW.",
        allowed_tools=["read_file", "grep_search", "list_dir"],
        max_steps=8,
        timeout=120.0,
        read_only=True,
        tags=["security", "review"],
    ),
    "code-reviewer": SubAgentSpec(
        name="code-reviewer",
        description="General code review — logic errors, style, test coverage, edge cases",
        system_prompt="You are a senior engineer reviewing code. Check for: logic errors, "
                      "edge cases, style guide violations, missing error handling, "
                      "test coverage gaps, performance issues.",
        allowed_tools=["read_file", "grep_search", "list_dir"],
        max_steps=8,
        timeout=120.0,
        read_only=True,
        tags=["review"],
    ),
    "documenter": SubAgentSpec(
        name="documenter",
        description="Generate documentation from code — docstrings, README, API reference",
        system_prompt="You are a technical writer. Read the code and generate documentation. "
                      "Focus on: public API surface, usage examples, edge cases, parameter descriptions.",
        allowed_tools=["read_file", "list_dir"],
        max_steps=6,
        timeout=90.0,
        read_only=True,
        tags=["docs"],
    ),
    "data-analyst": SubAgentSpec(
        name="data-analyst",
        description="Analyze data files, logs, or structured output for patterns and anomalies",
        system_prompt="You are a data analyst. Read the provided data, identify patterns, "
                      "anomalies, and trends. Summarize findings with specific evidence.",
        allowed_tools=["read_file", "grep_search"],
        max_steps=6,
        timeout=90.0,
        read_only=True,
        tags=["data"],
    ),
    "architect": SubAgentSpec(
        name="architect",
        description="Architecture review — dependency analysis, module boundaries, design patterns",
        system_prompt="You are a software architect. Review the codebase structure. "
                      "Check for: circular dependencies, violation of layer boundaries, "
                      "missing abstractions, over-engineering, architectural drift.",
        allowed_tools=["read_file", "grep_search", "list_dir"],
        max_steps=10,
        timeout=180.0,
        read_only=True,
        tags=["architecture", "review"],
    ),
    "helper": SubAgentSpec(
        name="helper",
        description="General-purpose assistant — answer questions, explain code, suggest fixes",
        system_prompt="You are a helpful engineering assistant. Answer questions, explain code, "
                      "suggest fixes, and provide examples. Be concise and specific.",
        allowed_tools=["read_file", "grep_search", "list_dir"],
        max_steps=5,
        timeout=60.0,
        read_only=False,
        tags=["general"],
    ),
    "refactor-agent": SubAgentSpec(
        name="refactor-agent",
        description="Refactor code — rename symbols, extract methods, split files, apply patterns",
        system_prompt="You are a senior software engineer performing code refactoring. "
                      "Read the target code, plan the refactoring steps, then execute them. "
                      "Ensure all tests still pass after each change.",
        allowed_tools=["read_file", "grep_search", "list_dir", "edit", "write_file"],
        max_steps=12,
        timeout=180.0,
        read_only=False,
        sandbox_profile="safe",
        tags=["refactor", "write"],
        post_actions=[{"type": "scout", "prompt": "Verify the refactoring in {spec}:\n"
                       "1. Did any test break? {result}\n"
                       "2. Are there any syntax errors?\n"
                       "3. Does the change preserve existing behavior?"}],
    ),
    "fixer": SubAgentSpec(
        name="fixer",
        description="Fix bugs and issues — read error, locate cause, apply fix, verify",
        system_prompt="You are a debug technician. Read the error description, locate the root cause "
                      "in the codebase, apply the minimal fix, and verify the fix doesn't break tests. "
                      "Explain what caused the bug and how your fix resolves it.",
        allowed_tools=["read_file", "grep_search", "list_dir", "edit", "write_file", "shell"],
        max_steps=10,
        timeout=180.0,
        read_only=False,
        sandbox_profile="safe",
        tags=["fix", "write"],
        post_actions=[{"type": "scout", "prompt": "Verify the fix for {spec}:\n"
                       "1. Does the fix actually address {answer}?\n"
                       "2. Are there any side effects?\n"
                       "3. Do existing tests pass?"}],
    ),
}
