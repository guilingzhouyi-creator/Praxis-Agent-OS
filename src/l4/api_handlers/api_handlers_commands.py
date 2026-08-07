"""Command management API handlers — register/unregister/list user commands.

Endpoints:
  GET    /api/v1/commands         — list all commands (system + user)
  POST   /api/v1/commands         — register a user command
  DELETE /api/v1/commands/{name}  — unregister a user command
  PUT    /api/v1/commands/{name}  — update a user command's metadata
"""

from __future__ import annotations


def handle_commands_list(body: dict | None = None) -> dict:
    """GET /api/v1/commands — list all registered commands with metadata."""
    from l1.kernel.commands import get_registry

    reg = get_registry()
    category = (body or {}).get("category", "") if body else ""
    return {
        "success": True,
        "count": len(reg.list(category=category)),
        "commands": reg.list(category=category),
        "stats": reg.stats(),
    }


def handle_commands_register(body: dict | None = None) -> dict:
    """POST /api/v1/commands — register a custom user command.

    Body:
      name:       Command name (without /)
      help:       Help text (required)
      category:   Optional category (default "custom")
      aliases:    Optional list of aliases
      args:       Optional list of arg schemas
    """
    b = body or {}
    name = b.get("name", "")
    help_text = b.get("help", "")
    if not name or not help_text:
        return {"success": False, "error": "name and help required"}

    from l1.kernel.commands import get_registry

    reg = get_registry()

    # Build a simple passthrough handler
    def _handler(args: list[str]) -> dict:
        return {"success": True, "output": f"{name}: executed with {args}"}

    return reg.register_user(
        name,
        _handler,
        {
            "help": help_text,
            "category": b.get("category", "custom"),
            "aliases": b.get("aliases", []),
            "args": b.get("args", []),
        },
    )


def handle_commands_remove(name: str = "") -> dict:
    """DELETE /api/v1/commands/{name} — unregister a user command."""
    if not name:
        return {"success": False, "error": "name required"}
    from l1.kernel.commands import get_registry

    return get_registry().unregister(name)


def handle_commands_update(name: str = "", body: dict | None = None) -> dict:
    """PUT /api/v1/commands/{name} — update a user command's metadata."""
    if not name:
        return {"success": False, "error": "name required"}
    b = body or {}
    from l1.kernel.commands import get_registry

    reg = get_registry()

    if reg.is_system(name):
        return {"success": False, "error": f"cannot modify system command: {name}"}

    # Unregister and re-register with updated metadata
    existing = reg.get(name)
    if existing is None:
        return {"success": False, "error": f"command not found: {name}"}

    handler = reg.get_handler(name)
    if handler is None:
        return {"success": False, "error": f"no handler for: {name}"}

    reg.unregister(name)
    return reg.register_user(
        name,
        handler,
        {
            "help": b.get("help", existing.help),
            "category": b.get("category", existing.category),
            "aliases": b.get("aliases", existing.aliases),
            "args": b.get("args", existing.args),
        },
    )
