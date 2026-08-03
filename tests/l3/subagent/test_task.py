"""Tests for subagent_task.py — SubAgentTask execution and model kwargs."""
from __future__ import annotations

from l3.agent.subagent_spec import SubAgentSpec
from l3.agent.subagent_task import SubAgentTask


def test_subagent_task_creation():
    """A SubAgentTask can be created with required fields."""
    spec = SubAgentSpec(name="test-agent", description="Test agent")
    task = SubAgentTask(task_id="test-t-1", spec=spec, prompt="test task")
    assert task.id is not None
    assert task.id == "test-t-1"
    assert task.spec.name == "test-agent"


def test_subagent_task_resolve_model_kwargs_default():
    """resolve_model_kwargs returns a dict with default profile name."""
    spec = SubAgentSpec(name="default-agent", description="Default")
    task = SubAgentTask(task_id="test-t-2", spec=spec, prompt="test")
    kwargs = task.resolve_model_kwargs()
    assert isinstance(kwargs, dict)


def test_subagent_task_resolve_model_kwargs_with_override():
    """resolve_model_kwargs accepts per-spec model_config overrides."""
    spec = SubAgentSpec(
        name="override-agent", description="Override",
        model_spec="custom_profile",
        model_config={"temperature": 0.5},
    )
    task = SubAgentTask(task_id="test-t-3", spec=spec, prompt="test")
    kwargs = task.resolve_model_kwargs()
    assert isinstance(kwargs, dict)


def test_subagent_task_status_lifecycle():
    """SubAgentTask progresses through expected statuses."""
    spec = SubAgentSpec(name="lifecycle-agent", description="Lifecycle")
    task = SubAgentTask(task_id="test-t-4", spec=spec, prompt="test")
    assert task.status == "pending"
    task.status = "running"
    assert task.status == "running"
    task.status = "completed"
    assert task.status == "completed"
