"""API handler mixin — unified card types / plan endpoints.

Module-level functions consumed by the ApiHandlers mixin in
``api_handlers/__init__.py``.
"""

from __future__ import annotations


def card_types_list(body: dict | None = None) -> dict:
    """List registered unified card types."""
    from l3.card.card_unified import list_card_types

    return {"success": True, "types": list_card_types()}


def card_types_register(body: dict) -> dict:
    """Register a new unified card type."""
    from l3.card.card_unified import register_card_type

    name = body.get("name", "")
    defn = body.get("definition", {})
    if not name or not defn:
        return {"error": "name and definition are required"}
    register_card_type(name, defn)
    return {"success": True, "name": name}


def card_unified_submit(body: dict) -> dict:
    """Submit a unified (nature/phase/task) card."""
    from l3.card.card_unified import CardSummary, CardUnified

    card = CardUnified(nature=body.get("nature", "execution"), priority=body.get("priority", 5))
    card.summary = CardSummary(
        title=body.get("title", ""), description=body.get("description", ""), columns=body.get("columns", {})
    )
    for pd in body.get("phases", []):
        phase = card.add_phase(
            name=pd.get("name", ""),
            mode=pd.get("mode", "single"),
            agents=pd.get("agents", []),
            review_prompt=pd.get("review_prompt", ""),
        )
        for td in pd.get("tasks", []):
            card.add_task(
                phase_name=phase.name,
                action=td.get("action", ""),
                target=td.get("target", ""),
                params=td.get("params", {}),
                agent=td.get("agent", ""),
            )
    card.submit()
    return {"success": True, "card": card.to_dict(include_hidden=False)}


def card_plan(body: dict) -> dict:
    """Fetch a card's plan by id."""
    from l3.card.card_registry import get_registry

    card_id = body.get("card_id", "")
    if not card_id:
        return {"error": "card_id required"}
    return get_registry().get_card_plan(card_id)


def submit_batch_preserving(body: dict) -> dict:
    """Submit a batch of intents preserving the legacy response shape.

    Kept distinct from ``api/api_handlers_cards.submit_batch`` (which returns
    ``submitted``/``card_ids``) so existing clients relying on ``count`` keep
    working unchanged.
    """
    try:
        from l3.card.card_registry import get_registry

        cards = body.get("cards", [])
        ids = [get_registry().submit(c.get("intent", ""), c.get("domain", "")) for c in cards]
        return {"success": True, "card_ids": ids, "count": len(ids)}
    except Exception as e:
        return {"error": str(e)}
