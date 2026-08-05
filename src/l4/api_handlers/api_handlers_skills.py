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
from typing import Any

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
    skills = sm.list(tags=tags, limit=limit)
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
    r = _manager().create(
        name=name,
        description=b.get("description", ""),
        prompt=b.get("prompt", ""),
        tags=b.get("tags"),
        rules=b.get("rules"),
        procedures=b.get("procedures"),
        agent_id=agent_id,
        role=role,
    )
    return r


def handle_skills_update(body: dict | None = None, name: str = "") -> dict:
    """PUT /api/skills/:name — update skill (developer-only)."""
    if not name:
        return {"success": False, "error": "skill name is required"}
    b = body or {}
    agent_id, role = _caller(b)
    data = {k: v for k, v in b.items() if k in ("description", "prompt", "rules", "procedures", "tags") and v is not None}
    if not data:
        return {"success": False, "error": "no updatable fields provided"}
    r = _manager().update(name, data, agent_id=agent_id, role=role)
    return r


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
