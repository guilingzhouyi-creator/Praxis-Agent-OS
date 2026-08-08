"""Skill tools — list_skills, use_skill for L2 Shell / AgentLoop."""

import logging

from l1.kernel.params.system import LOG_TRUNC_60, SKILL_POSTURE_OFFENSIVE

logger = logging.getLogger(__name__)


def list_skills(args: dict, agent_id: str) -> dict:
    """List available skills, optionally filtered by tag or tool name.

    Audience routing: skills tagged "strategy" are visible to the L3A
    central layer only; "execution" skills to Cell peer agents; untagged
    (system knowledge) skills are universal. Dynamic supply — the agent
    pulls what its domain needs instead of receiving everything injected.

    Usage:
      list_skills()                          → all skills visible to me
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
        results = sm.list_skills(tags=tags, limit=limit)

    from l1.kernel.skill import skill_visible

    visible = [s for s in results if skill_visible(s, agent_id)]

    return {"success": True, "skills": visible, "count": len(visible), "audience": _audience_label(agent_id)}


def _audience_label(agent_id: str) -> str:
    """Human label of the agent's audience domain."""
    from l1.kernel.skill import audience_of

    return audience_of(agent_id)


def use_skill(args: dict, agent_id: str) -> dict:
    """Execute a skill by name; returns the structured agent-facing view.

    Usage:
      use_skill(name="refactor", function_name="validate", goal="split")
      use_skill(name="tdd", structured=true)  → structured view (default)
      use_skill(name="tdd", full=true)        → full body (write-gated)

    The structured view (rules/procedures/stages as machine-readable items,
    no markdown body) is the runtime contract; the full body is a privileged
    read for the human/review layer. Audience routing: a skill tagged for
    another domain is refused.
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

    from l1.kernel.skill import skill_visible

    if not skill_visible(skill_data, agent_id):
        return {"success": False, "error": f"skill '{name}' is not in the {_audience_label(agent_id)} domain"}

    # Posture gate (default-deny, runtime policy): offensive-posture skills
    # require the SkillManager offensive policy to authorize the driving card
    # nature. The tool pipeline forwards the card nature as ``_card_nature``;
    # disabling the policy at runtime bypasses the gate (soft control).
    if skill_data.get("posture") == SKILL_POSTURE_OFFENSIVE:
        nature = str(args.get("_card_nature", ""))
        if not get_skill_manager().offensive_authorized(nature):
            # P1: record use_skill posture denials in StatsCenter.
            try:
                from l3.tool_system.security_mode import ingest_security_metric

                ingest_security_metric("security.gate.use_skill.blocked", tags={"skill": name, "nature": nature})
            except Exception:
                pass
            return {
                "success": False,
                "error": f"skill '{name}' is offensive-posture and requires card authorization"
                f" (nature '{nature}' not allowed by offensive policy)",
            }

    # Structured agent-facing view is the default contract (rules/procedures/
    # stages as machine-readable items — no markdown body). The full body is a
    # privileged read (full=True, write gate) for the human/review layer.
    structured = bool(args.get("structured", True))
    full = bool(args.get("full", False))

    if full:
        ok, who = sm.authorize_write(args.get("_agent_id", ""), args.get("_role", ""))
        if not ok:
            return {"success": False, "error": f"permission denied: {who}"}
        variables = skill_data.get("variables", [])
        expanded = skill_data.get("prompt", "")
        for v in variables or []:
            val = args.get(v.lower(), "")
            if val:
                expanded = expanded.replace(f"${v.upper()}", str(val))
        sm.bump_usage(name)
        return {
            "success": True,
            "skill": name,
            "prompt": expanded,
            "description": skill_data.get("description", "")[:LOG_TRUNC_60],
            "full": True,
            "variables": variables or [],
            "allowed_tools": skill_data.get("allowed_tools") or [],
        }

    if structured:
        view = sm.structured_skill(name, agent_id)
        if not view.get("success"):
            return {"success": False, "error": view.get("error", "skill unavailable")}
        sm.bump_usage(name)
        view["skill"] = name
        return view

    # Legacy raw mode: current stage instructions for staged skills, else the
    # full body (explicit opt-out from the structured contract).
    stage_info: dict = {}
    if skill_data.get("stages"):
        stage_info = sm.current_stage(name, agent_id)
        stage = stage_info.get("stage") or {}
        prompt = stage.get("instructions") or skill_data.get("prompt", "")
    else:
        prompt = skill_data.get("prompt", "")
    variables = skill_data.get("variables", [])
    allowed_tools = skill_data.get("allowed_tools")

    # Expand variables: $VAR_NAME → args["var_name"] (case-insensitive)
    expanded = prompt
    for v in variables or []:
        val = args.get(v.lower(), "")
        if val:
            expanded = expanded.replace(f"${v.upper()}", str(val))

    # Record usage atomically — bump_usage does the read-modify-write under a
    # single lock so concurrent use_skill calls never lose an increment.
    sm.bump_usage(name)

    result = {
        "success": True,
        "skill": name,
        "prompt": expanded,
        "description": skill_data.get("description", "")[:LOG_TRUNC_60],
        "variables": variables or [],
        "allowed_tools": allowed_tools or [],
    }
    if stage_info:
        result["staged"] = True
        result["stage_index"] = stage_info.get("stage_index", 0)
        result["stage_id"] = (stage_info.get("stage") or {}).get("id", "")
        result["next_stage"] = stage_info.get("next_stage")
    return result
