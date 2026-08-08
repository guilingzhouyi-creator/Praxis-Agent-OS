"""Config section handlers — agent / loop / l3a / skill domains.

Each ``cfg_*`` handler processes one section of praxis.yaml and applies its
values to the corresponding agent/loop configuration. Re-exported by
``config_handlers.py``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from l1.kernel.params.agent import (  # noqa: E402
    AGENT_CLEARANCE,
    DEFAULT_AGENT_CONFIGS,
    TERRITORY_MAP,
    TERRITORY_PATHS,
)


def cfg_territories(cfg: dict, s: Any, results: dict) -> None:
    """Load role-to-path territory maps and rebuild the path→role lookup."""
    TERRITORY_MAP.clear()
    TERRITORY_PATHS.clear()
    for role, paths in cfg.items():
        TERRITORY_PATHS[role] = paths
        for p in paths:
            TERRITORY_MAP[p] = role
    results["territories"] = len(cfg)


def cfg_clearance(cfg: dict, s: Any, results: dict) -> None:
    """Load agent clearance rules into the global clearance map."""
    AGENT_CLEARANCE.clear()
    AGENT_CLEARANCE.update(cfg)
    results["clearance"] = len(cfg)


def cfg_agent_role_map(cfg: dict, s: Any, results: dict) -> None:
    """Load AGENT_ROLE_MAP from praxis.yaml agent_role_map: section.

    Format:
      agent_role_map:
        1: "reader"
        2: "writer"
        3: "reviewer"

    Maps tool ring level → agent role name for HTN-C inference.
    """
    from l1.kernel.params.agent import AGENT_ROLE_MAP

    role_map = dict(AGENT_ROLE_MAP)
    for ring_str, role in cfg.items():
        try:
            role_map[int(ring_str)] = str(role)
        except (ValueError, TypeError):
            continue
    results["agent_role_map"] = len(role_map)


def cfg_agent_priority(cfg: dict, s: Any, results: dict) -> None:
    """Load AGENT_PRIORITY from praxis.yaml agent_priority: section.

    Format:
      agent_priority:
        reader:   5
        writer:   5
        reviewer: 5
    """
    from l1.kernel.params.agent import AGENT_PRIORITY

    priority = dict(AGENT_PRIORITY)
    priority.update(cfg)
    results["agent_priority"] = len(cfg)


def cfg_agents(cfg: dict, s: Any, results: dict) -> None:
    """Load per-role agent defaults into the global agent config map."""
    from l1.kernel.params.agent import AgentDefaults

    for role, cdict in cfg.items():
        mc = cdict.get("model_config", None)
        spk = cdict.get("system_prompt_key", "")
        DEFAULT_AGENT_CONFIGS[role] = AgentDefaults(
            max_scouts=cdict.get("max_scouts", 3),
            ring=cdict.get("ring", 1),
            model_config=mc if isinstance(mc, dict) else None,
            system_prompt_key=str(spk) if spk else "",
        )
    results["agents"] = len(cfg)


def cfg_think(cfg: dict, s: Any, results: dict) -> None:
    """Load think quota max budget / max reasoning from praxis.yaml think: section."""
    from l3.config.settings_center import get_center

    center = get_center()
    if "max_budget" in cfg:
        center.set_l2("think.max_budget", int(cfg["max_budget"]))
    if "max_reasoning" in cfg:
        center.set_l2("think.max_reasoning", str(cfg["max_reasoning"]))
    if "profiles" in cfg and isinstance(cfg["profiles"], dict):
        center.set_l2("think.profiles", cfg["profiles"])
    results["think"] = True


def cfg_loop_control(cfg: dict, s: Any, results: dict) -> None:
    """Load loop control parameters from praxis.yaml loop_control: section."""
    from l3.config.settings_center import get_center

    center = get_center()
    mapping = {
        "max_steps": "loop.max_steps",
        "timeout": "loop.timeout",
        "max_iterations": "loop.max_iterations",
        "max_attempts": "loop.max_attempts",
        "continuation_nudge": "loop.continuation_nudge",
        "tool_repeat_warn": "loop.tool_repeat_warn",
        "tool_repeat_stop": "loop.tool_repeat_stop",
        "coarse_repeat_nudge": "loop.coarse_repeat_nudge",
        "coarse_repeat_stop": "loop.coarse_repeat_stop",
        "verify_cadence": "loop.verify_cadence",
    }
    for cfg_key, center_key in mapping.items():
        if cfg_key in cfg:
            center.set_l2(center_key, cfg[cfg_key])

    if "scope" in cfg:
        center.set_l2("loop.scope", cfg["scope"])
    if "enabled" in cfg:
        center.set_l2("loop.enabled", bool(cfg["enabled"]))
    # Auto-test switch: auto_test.py reads get_tool_config("loop.auto_test"),
    # so the YAML value must land in the discovery "tool" registry too.
    # YAML 1.1 parses bare `off` as boolean False — map booleans back to the
    # canonical string modes.
    if "auto_test" in cfg:
        from l1.kernel.discovery import set_config as _set_cfg

        raw = cfg["auto_test"]
        mode = ("async" if raw else "off") if isinstance(raw, bool) else str(raw).lower()
        _set_cfg("tool", "loop.auto_test", mode)
        center.set_l2("loop.auto_test", mode)
    results["loop_control"] = True


def cfg_harness(cfg: dict, s: Any, results: dict) -> None:
    """Load harness: section (harness.py reads get_tool_config("harness_mode"))."""
    from l1.kernel.discovery import set_config as _set_cfg

    if isinstance(cfg, dict) and "mode" in cfg:
        mode = str(cfg["mode"]).lower()
        _set_cfg("tool", "harness_mode", mode)
        s.set_l2("harness.mode", mode)
    results["harness"] = True


def cfg_l3a(cfg: dict, s: Any, results: dict) -> None:
    """Load L3A session limits from praxis.yaml l3a: section."""
    from l3.config.settings_center import get_center

    center = get_center()
    mapping = {
        "max_steps": "l3a.max_steps",
        "max_turns": "l3a.max_turns",
        "timeout": "l3a.timeout",
        "idle_timeout": "l3a.idle_timeout",
        "archive_importance": "l3a.archive_importance",
    }
    for yaml_key, sc_key in mapping.items():
        if yaml_key in cfg:
            center.set_l2(sc_key, cfg[yaml_key])
    results["l3a"] = True


def cfg_skill(cfg: dict, s: Any, results: dict) -> None:
    """Load skill write-gate policy + evolution scope from praxis.yaml skill: section.

    Mirrors the values into SettingsCenter L2 and injects them into the
    SkillManager (L1) so runtime writes honor the developer gate.

    Supported keys:
      - write_min_ring / write_roles : developer write gate (existing)
      - evolve_scope                 : "project" | "global" — where evolved
                                       skills are persisted (default project)
      - project_dirs                 : extra project skill discovery dirs,
                                       appended to config/discovery skill_dirs
      - offensive_enabled            : master switch for the offensive-posture
                                       gate (soft control; runtime-switchable
                                       via the API)
      - offensive_natures            : card natures that authorize injecting
                                       offensive-posture skills
    """
    from l1.kernel.skill import get_skill_manager
    from l3.config.settings_center import get_center

    center = get_center()
    if isinstance(cfg, dict):
        if "auto_activate_builtin" in cfg:
            center.set_l2("skill.auto_activate_builtin", bool(cfg["auto_activate_builtin"]))
        if "write_min_ring" in cfg:
            try:
                center.set_l2("skill.write_min_ring", int(cfg["write_min_ring"]))
            except (TypeError, ValueError):
                logger.warning("cfg_skill: invalid write_min_ring %r ignored", cfg["write_min_ring"])
        if "write_roles" in cfg and isinstance(cfg["write_roles"], list):
            center.set_l2("skill.write_roles", [r for r in cfg["write_roles"] if isinstance(r, str)])
        if "evolve_scope" in cfg and cfg["evolve_scope"] in ("project", "global"):
            center.set_l2("skill.evolve_scope", cfg["evolve_scope"])
        if "retriever_backend" in cfg and cfg["retriever_backend"] in ("tfidf", "embedding"):
            center.set_l2("skill.retriever_backend", cfg["retriever_backend"])
        if "project_dirs" in cfg and isinstance(cfg["project_dirs"], list):
            center.set_l2("skill.project_dirs", cfg["project_dirs"])
            # Push extra discovery dirs into the paths singleton so
            # load_builtin() finds project skills at boot.
            try:
                from l1.kernel.paths import get_paths

                p = get_paths()
                existing = list(getattr(p, "skill_dirs", []) or [])
                for d in cfg["project_dirs"]:
                    if d not in existing:
                        existing.append(d)
                p.skill_dirs = existing
            except Exception:
                logger.debug("cfg_skill: project_dirs path push skipped")
        if "offensive_enabled" in cfg:
            center.set_l2("skill.offensive_enabled", bool(cfg["offensive_enabled"]))
        if "offensive_natures" in cfg and isinstance(cfg["offensive_natures"], list):
            center.set_l2("skill.offensive_natures", [n for n in cfg["offensive_natures"] if isinstance(n, str)])
        if "attack" in cfg and isinstance(cfg["attack"], dict):
            domains = cfg["attack"].get("domains")
            if isinstance(domains, dict):
                clean = {
                    str(k): [s for s in v if isinstance(s, str)] for k, v in domains.items() if isinstance(v, list)
                }
                center.set_l2("team.attack.domains", clean)
    get_skill_manager().set_write_policy(
        min_ring=center.get("skill.write_min_ring", None),
        roles=center.get("skill.write_roles", None),
    )
    get_skill_manager().set_offensive_policy(
        enabled=center.get("skill.offensive_enabled", None),
        natures=center.get("skill.offensive_natures", None),
    )
    _sub_switches = {}
    for _k in ("generalize", "llm_distill", "clustering", "sampling"):
        _v = center.get(f"skill.distill_sub.{_k}", None)
        if _v is not None:
            _sub_switches[_k] = bool(_v)
    get_skill_manager().set_distill_policy(
        distill=center.get("skill.distill_enabled", None),
        dpo_signal=center.get("skill.dpo_signal_enabled", None),
        sub=_sub_switches or None,
        source="config",
    )
    results["skill"] = True
