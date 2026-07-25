"""YAML card loader — reads snake_card.yaml into a structured Card."""
from __future__ import annotations

import os
from typing import Any

from .card import Card, CardMode, Phase, PhaseMode, Step


def load_card(path: str) -> dict:
    """Load a card definition from YAML file. Returns {"success": bool, "card": Card}."""
    import yaml
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        return {"success": False, "error": f"yaml parse: {e}"}

    cd = data.get("card", {})
    if not cd:
        return {"success": False, "error": "no 'card' key in yaml"}

    mode_str = cd.get("mode", "EXECUTE").upper()
    mode_map = {"EXECUTE": CardMode.EXECUTE, "ISSUE": CardMode.ISSUE,
                "PARALLEL_ALL": CardMode.PARALLEL_ALL}
    mode = mode_map.get(mode_str, CardMode.EXECUTE)

    phases = []
    for pd in data.get("phases", cd.get("phases", [])):
        pm_str = pd.get("mode", "SEQUENTIAL").upper()
        pm = PhaseMode.PARALLEL if pm_str == "PARALLEL" else PhaseMode.SEQUENTIAL

        steps = []
        for sd in pd.get("steps", []):
            verify = sd.get("verify")
            if verify and isinstance(verify, dict):
                verify["template"] = verify.get("template", "scout")
            step = Step(
                action=sd.get("action", "think"),
                target=sd.get("target", ""),
                params=sd.get("params", {}),
                agent=sd.get("agent", ""),
                verify=verify,
            )
            steps.append(step)

        phases.append(Phase(name=pd.get("name", ""), mode=pm, steps=steps))

    card = Card(
        id=cd.get("id", "card-yaml"),
        intent=cd.get("intent", ""),
        domain=cd.get("domain", ""),
        mode=mode,
        phases=phases,
    )
    return {"success": True, "card": card}
