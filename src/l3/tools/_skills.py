"""Skill tools — list_skills, use_skill for L2 Shell / AgentLoop."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def list_skills(args: dict, agent_id: str) -> dict:
    """List available skills, optionally filtered by tag or tool name.

    Usage:
      list_skills()                          → all skills
      list_skills(tag="evolved")             → evolved skills only
      list_skills(tool="edit")               → skills that allow edit tool
    """
    try:
        from l1.kernel.skill import get_skill_manager
        sm = get_skill_manager()
    except Exception as e:
        return {"success": False, "error": f"skill manager unavailable: {e}"}

    tag = args.get("tag", "")
    tool = args.get("tool", "")
    limit = int(args.get("limit", 0))

    if tool:
        results = sm.list_by_allowed_tools(tool)
    else:
        tags = [tag] if tag else None
        results = sm.list(tags=tags, limit=limit)

    return {"success": True, "skills": results, "count": len(results)}


def use_skill(args: dict, agent_id: str) -> dict:
    """Execute a skill by name with optional variable substitution.

    Usage:
      use_skill(name="refactor", function_name="validate", goal="split")
      → expands $FUNCTION_NAME and $GOAL in the skill's prompt

    Returns the expanded prompt text. The caller (AgentLoop) should
    inject it as a system message for the LLM.
    """
    name = args.get("name", "")
    if not name:
        return {"success": False, "error": "skill name is required"}

    try:
        from l1.kernel.skill import get_skill_manager
        sm = get_skill_manager()
    except Exception as e:
        return {"success": False, "error": f"skill manager unavailable: {e}"}

    skill_data = sm.get(name)
    if not skill_data:
        return {"success": False, "error": f"skill '{name}' not found"}

    prompt = skill_data.get("prompt", "")
    variables = skill_data.get("variables", [])
    allowed_tools = skill_data.get("allowed_tools")

    # Expand variables: $VAR_NAME → args["var_name"] (case-insensitive)
    expanded = prompt
    for v in variables or []:
        val = args.get(v.lower(), "")
        if val:
            expanded = expanded.replace(f"${v.upper()}", str(val))

    # Record usage
    sm.update(name, {"last_used": __import__("time").time()})

    return {
        "success": True,
        "skill": name,
        "prompt": expanded,
        "description": skill_data.get("description", "")[:60],
        "variables": variables or [],
        "allowed_tools": allowed_tools or [],
    }
