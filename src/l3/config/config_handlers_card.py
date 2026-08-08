"""Config section handlers — card / memory domains.

Each ``cfg_*`` handler processes one section of praxis.yaml and applies its
values to the corresponding card/memory configuration. Re-exported by
``config_handlers.py``.
"""

from __future__ import annotations

from typing import Any


def cfg_card_pool(cfg: dict, s: Any, results: dict) -> None:
    """Load card pool registry config from praxis.yaml card_pool: section.

    No runtime consumer yet — expose to SettingsCenter L2 for API querying.
    """
    from l3.config.settings_center import get_center

    center = get_center()
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            center.set_l2(f"card_pool.{k}", v)
    results["card_pool"] = True


def cfg_card_gate(cfg: dict, s: Any, results: dict) -> None:
    """Load card gate config from praxis.yaml → card_gate: section."""
    try:
        from l3.card.card_gate import load_config

        load_config(cfg if isinstance(cfg, dict) else {})
        results["card_gate"] = True
    except Exception as e:
        results["card_gate"] = f"error: {e}"


def cfg_card_types(cfg: dict, s: Any, results: dict) -> None:
    """Load card type definitions from praxis.yaml → card_types: section."""
    from l3.card.card_unified import load_card_types

    load_card_types(cfg if isinstance(cfg, dict) else {})
    results["card_types"] = len(cfg) if isinstance(cfg, dict) else 0


def cfg_memory(cfg: dict, s: Any, results: dict) -> None:
    """Load memory section from praxis.yaml (memory.graph.enabled etc.).

    Consumers (memory_graph.py) read the value via get_settings(), so mirror
    it into SettingsCenter L2 (the praxis.yaml layer).
    """
    if not isinstance(cfg, dict):
        results["memory"] = False
        return
    if isinstance(cfg.get("graph"), dict) and "enabled" in cfg["graph"]:
        s.set_l2("memory.graph.enabled", bool(cfg["graph"]["enabled"]))
    results["memory"] = True


def cfg_content_trust(cfg: dict, s: Any, results: dict) -> None:
    """Load content trust policies from praxis.yaml -> content_trust: section."""
    from l3.services.content_trust import load_policies

    load_policies(cfg if isinstance(cfg, dict) else {})
    results["content_trust"] = len(cfg) if isinstance(cfg, dict) else 0
