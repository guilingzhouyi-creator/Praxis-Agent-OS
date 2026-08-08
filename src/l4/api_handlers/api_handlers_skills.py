"""Skill management API — list/read skills (public) and create/update/delete (developer-only).

Read endpoints are open to any authenticated caller; mutation endpoints
enforce the SkillManager developer write gate (see SkillManager.authorize_write,
configured via SettingsCenter ``skill.write_min_ring`` / ``skill.write_roles``).

Endpoints (served by ApiGateway under /api/skills):
  GET    /api/skills            → list skills (optional ?tag= / ?limit=)
  GET    /api/skills/:name      → skill detail
  POST   /api/skills            → create skill (developer)   body: {name, description, prompt, rules?, tags?}
  PUT    /api/skills/:name      → update skill (developer)   body: {description?, prompt?, rules?}
  DELETE /api/skills/:name      → delete skill (developer)
  POST   /api/skills/reload     → reload built-in skills (developer)
  GET    /api/skills/permissions → current write-gate policy
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _manager():
    from l1.kernel.skill import get_skill_manager

    return get_skill_manager()


def _caller(body: dict | None) -> tuple[str, str]:
    """Extract (agent_id, role) from request body, if provided."""
    b = body or {}
    return str(b.get("agent_id", "")), str(b.get("role", ""))


def handle_skills_list(body: dict | None = None) -> dict:
    """GET /api/skills — list skills, optionally filtered."""
    b = body or {}
    sm = _manager()
    tag = b.get("tag", "")
    limit = int(b.get("limit", 0))
    tags = [tag] if tag else None
    skills = sm.list_skills(tags=tags, limit=limit)
    return {"success": True, "skills": skills, "count": len(skills)}


def handle_skills_get(body: dict | None = None, name: str = "") -> dict:
    """GET /api/skills/:name — skill detail."""
    if not name:
        return {"success": False, "error": "skill name is required"}
    skill = _manager().get(name)
    if not skill:
        return {"success": False, "error": f"skill '{name}' not found"}
    return {"success": True, "skill": skill}


def handle_skills_create(body: dict | None = None) -> dict:
    """POST /api/skills — create skill (developer-only)."""
    b = body or {}
    name = b.get("name", "")
    if not name:
        return {"success": False, "error": "skill name is required"}
    agent_id, role = _caller(b)
    return _manager().create(
        name=name,
        description=b.get("description", ""),
        prompt=b.get("prompt", ""),
        tags=b.get("tags"),
        rules=b.get("rules"),
        procedures=b.get("procedures"),
        agent_id=agent_id,
        role=role,
    )


def handle_skills_update(body: dict | None = None, name: str = "") -> dict:
    """PUT /api/skills/:name — update skill (developer-only)."""
    if not name:
        return {"success": False, "error": "skill name is required"}
    b = body or {}
    agent_id, role = _caller(b)
    data = {
        k: v for k, v in b.items() if k in ("description", "prompt", "rules", "procedures", "tags") and v is not None
    }
    if not data:
        return {"success": False, "error": "no updatable fields provided"}
    return _manager().update(name, data, agent_id=agent_id, role=role)


def handle_skills_delete(body: dict | None = None, name: str = "") -> dict:
    """DELETE /api/skills/:name — delete skill (developer-only)."""
    if not name:
        return {"success": False, "error": "skill name is required"}
    agent_id, role = _caller(body)
    return _manager().delete(name, agent_id=agent_id, role=role)


def handle_skills_reload(body: dict | None = None) -> dict:
    """POST /api/skills/reload — reload built-in skills (developer-only)."""
    agent_id, role = _caller(body)
    sm = _manager()
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": f"permission denied: {who}"}
    count = sm.load_builtin()
    return {"success": True, "loaded": count, "authorized": who}


def handle_skills_permissions(body: dict | None = None) -> dict:
    """GET /api/skills/permissions — current write-gate policy."""
    return {"success": True, "policy": _manager().write_policy()}


def handle_skills_offensive_policy_get(body: dict | None = None) -> dict:
    """GET /api/skills/offensive-policy — current offensive-posture gate policy."""
    return {"success": True, "policy": _manager().offensive_policy()}


def handle_skills_offensive_policy_set(body: dict | None = None) -> dict:
    """POST /api/skills/offensive-policy — update the offensive-posture gate (developer).

    Body (both optional; only provided fields change):
      enabled: bool   — False bypasses the posture gate entirely (soft control)
      natures: [str]  — card natures that authorize offensive-skill injection

    Mirrors the new values into SettingsCenter (L2) so runtime reads stay in
    sync; the policy is applied atomically on the SkillManager.
    """
    b = body or {}
    agent_id, role = _caller(b)
    sm = _manager()
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": f"permission denied: {who}"}
    update = {"success": True}
    if "enabled" in b:
        # Parse booleans explicitly — bool("false") is True in Python, which
        # would invert the gate when clients send string form values.
        raw = b["enabled"]
        update["enabled"] = raw in (True, "true", 1, "1")
    if "natures" in b and isinstance(b["natures"], list):
        update["natures"] = [n for n in b["natures"] if isinstance(n, str)]
    policy = sm.set_offensive_policy(
        enabled=update.get("enabled"),
        natures=update.get("natures"),
    )
    # Mirror into SettingsCenter L2 so config-driven reads observe the change.
    try:
        from l3.config.settings_center import get_center

        center = get_center()
        if "enabled" in update:
            center.set_l2("skill.offensive_enabled", bool(update["enabled"]))
        if "natures" in update:
            center.set_l2("skill.offensive_natures", list(update["natures"]))
    except Exception:
        logger.debug("skills: offensive policy SettingsCenter mirror skipped", exc_info=True)
    policy["authorized"] = who
    return policy


def handle_skills_distill_policy_get(body: dict | None = None) -> dict:
    """GET /api/skills/distill-policy — current distillation/DPO master switches."""
    return {"success": True, "policy": _manager().distill_policy()}


def handle_skills_distill_policy_set(body: dict | None = None) -> dict:
    """POST /api/skills/distill-policy — update distillation/DPO switches (developer).

    Body (all optional; only provided fields change):
      distill: bool    — master: False disables generalization/distillation
      dpo_signal: bool — False disables card→skill preference weighting
      sub: {str: bool} — stage sub-switches:
          generalize   — rule generalization (lean cases → lessons skill)
          llm_distill  — LLM distillation (OFF → rule baseline, no LLM)
          clustering   — semantic shingle clustering (OFF → by-tool)
          sampling     — frequency/difficulty digest (OFF → flat digest)

    Mirrors the new values into SettingsCenter (L2) so config-driven reads
    stay in sync; applied atomically on the SkillManager.
    """
    b = body or {}
    agent_id, role = _caller(b)
    sm = _manager()
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": f"permission denied: {who}"}
    distill = b.get("distill")
    dpo = b.get("dpo_signal")
    sub = b.get("sub")
    sub_clean = None
    if isinstance(sub, dict):
        sub_clean = {k: bool(v) for k, v in sub.items() if isinstance(v, bool)}
    policy = sm.set_distill_policy(
        distill=distill if isinstance(distill, bool) else None,
        dpo_signal=dpo if isinstance(dpo, bool) else None,
        sub=sub_clean,
        source="api",
    )
    try:
        from l3.config.settings_center import get_center

        center = get_center()
        if isinstance(distill, bool):
            center.set_l2("skill.distill_enabled", distill)
        if isinstance(dpo, bool):
            center.set_l2("skill.dpo_signal_enabled", dpo)
        if sub_clean:
            for k, v in sub_clean.items():
                center.set_l2(f"skill.distill_sub.{k}", v)
    except Exception:
        logger.debug("skills: distill policy SettingsCenter mirror skipped", exc_info=True)
    policy["authorized"] = who
    return policy


def handle_skills_pipeline_get(body: dict | None = None) -> dict:
    """GET /api/v2/skills/pipeline — current retrieval/curation pipeline policy."""
    return {"success": True, "policy": _manager().pipeline_policy()}


def handle_skills_pipeline_set(body: dict | None = None) -> dict:
    """POST /api/v2/skills/pipeline — update retrieval/curation pipeline knobs (developer).

    Body (all optional; only provided fields change):
      retrieval: bool            — False disables task-similarity ranking
      curation: bool             — False disables contribution-based curation
      contrib_min_trials: int    — minimum injections before a verdict counts
      contrib_min_ratio: float   — useful/injected below this → retire
      retrieval_min_score: float — similarity floor for skill ranking

    Mirrors the new values into SettingsCenter (L2) so config-driven reads
    stay in sync; applied atomically on the SkillManager.
    """
    b = body or {}
    agent_id, role = _caller(b)
    sm = _manager()
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": f"permission denied: {who}"}
    update: dict = {}
    for key in ("retrieval", "curation"):
        if key in b:
            raw = b[key]
            update[key] = raw in (True, "true", 1, "1")
    if "contrib_min_trials" in b and isinstance(b["contrib_min_trials"], int):
        update["contrib_min_trials"] = b["contrib_min_trials"]
    if "contrib_min_ratio" in b and isinstance(b["contrib_min_ratio"], (int, float)):
        update["contrib_min_ratio"] = float(b["contrib_min_ratio"])
    if "retrieval_min_score" in b and isinstance(b["retrieval_min_score"], (int, float)):
        update["retrieval_min_score"] = float(b["retrieval_min_score"])
    policy = sm.set_pipeline_policy(**update, source="api")
    try:
        from l3.config.settings_center import get_center

        center = get_center()
        for key, value in update.items():
            center.set_l2(f"skill.pipeline.{key}", value)
    except Exception:
        logger.debug("skills: pipeline policy SettingsCenter mirror skipped", exc_info=True)
    policy["authorized"] = who
    return policy


def handle_skills_disclosure_get(body: dict | None = None) -> dict:
    """GET /api/v2/skills/disclosure — current progressive-disclosure policy."""
    return {"success": True, "policy": _manager().disclosure_policy()}


def handle_skills_disclosure_set(body: dict | None = None) -> dict:
    """POST /api/v2/skills/disclosure — update progressive-disclosure knobs (developer).

    Body (all optional; only provided fields change):
      full_index_enabled: bool       — append the full skill index after curated slots
      full_index_limit: int          — max entries in the full index
      audience_filter_enabled: bool  — strategy/execution audience routing
      strategy_capability_view: bool — L3A read-only view of execution capabilities

    Mirrors the new values into SettingsCenter (L2); applied atomically on
    the SkillManager.
    """
    b = body or {}
    agent_id, role = _caller(b)
    sm = _manager()
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": f"permission denied: {who}"}
    update: dict = {}
    for key in ("full_index_enabled", "audience_filter_enabled", "strategy_capability_view"):
        if key in b:
            raw = b[key]
            update[key] = raw in (True, "true", 1, "1")
    if "full_index_limit" in b and isinstance(b["full_index_limit"], int):
        update["full_index_limit"] = b["full_index_limit"]
    policy = sm.set_disclosure_policy(**update, source="api")
    try:
        from l3.config.settings_center import get_center

        center = get_center()
        for key, value in update.items():
            center.set_l2(f"skill.disclosure.{key}", value)
    except Exception:
        logger.debug("skills: disclosure policy SettingsCenter mirror skipped", exc_info=True)
    policy["authorized"] = who
    return policy


def handle_skills_guidance_get(body: dict | None = None) -> dict:
    """GET /api/v2/skills/guidance — current guidance operating mode."""
    return {"success": True, "policy": _manager().guidance_policy()}


def handle_skills_guidance_set(body: dict | None = None) -> dict:
    """POST /api/v2/skills/guidance — switch guidance operating mode (developer).

    Body: ``{"mode": "small"|"full"}`` — small treats the guidance fields
    (stages/next/dependencies) as inert (plain skills); full activates the
    atomic stage-granularity chains (frontier unlock, stage disclosure, TODO
    linkage). Mirrors into SettingsCenter (L2).
    """
    b = body or {}
    agent_id, role = _caller(b)
    sm = _manager()
    ok, who = sm.authorize_write(agent_id, role)
    if not ok:
        return {"success": False, "error": f"permission denied: {who}"}
    policy = sm.set_guidance_policy(mode=b.get("mode", ""), source="api")
    if not policy.get("success", True):
        return policy
    try:
        from l3.config.settings_center import get_center

        center = get_center()
        center.set_l2("skill.guidance.mode", policy.get("mode"))
    except Exception:
        logger.debug("skills: guidance policy SettingsCenter mirror skipped", exc_info=True)
    policy["authorized"] = who
    return policy
