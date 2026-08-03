"""YAML card loader — reads snake_card.yaml into a structured CardUnified."""
from __future__ import annotations

from .card_unified import CardPhase, CardSummary, CardTask, CardUnified, PhaseMode


def load_card(path: str) -> dict:
    """Load a card definition from YAML file. Returns {"success": bool, "card": CardUnified}."""
    import yaml
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        return {"success": False, "error": f"yaml parse: {e}"}

    cd = data.get("card", {})
    if not cd:
        return {"success": False, "error": "no 'card' key in yaml"}

    nature = cd.get("mode", "execution").lower()
    if nature in ("execute", "execution"):
        nature = "execution"
    elif nature in ("issue",):
        nature = "issue"
    elif nature in ("parallel_all",):
        nature = "parallel_all"

    phases: list[CardPhase] = []
    for pd in data.get("phases", cd.get("phases", [])):
        pm_str = pd.get("mode", "single").upper()
        pm = PhaseMode.MULTI if pm_str == "MULTI" else PhaseMode.SINGLE

        tasks: list[CardTask] = []
        for sd in pd.get("steps", []):
            tasks.append(CardTask(
                action=sd.get("action", "think"),
                target=sd.get("target", ""),
                params=sd.get("params", {}),
                agent=sd.get("agent", ""),
            ))

        phases.append(CardPhase(name=pd.get("name", ""), mode=pm, tasks=tasks))

    card = CardUnified(
        id=cd.get("id", "card-yaml"),
        priority=cd.get("priority", 5),
        nature=nature,
        phases=phases,
    )
    card.summary = CardSummary(
        title=cd.get("intent", ""),
        description="",
        columns={"domain": cd.get("domain", ".")},
    )
    return {"success": True, "card": card}
