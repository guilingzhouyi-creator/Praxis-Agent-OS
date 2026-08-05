"""CommandRegistry — unified shell command registry with system/user separation.

Architecture:
  System commands — registered by code, protected (cannot be deleted or modified).
  User commands   — registered via API or config, fully mutable.

Both types share the same metadata source: config/commands.yaml (defaults)
+ praxis.yaml commands: overrides + runtime API overrides.

The registry is a singleton.  Access via get_registry().
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field

import yaml

from l1.kernel.registry_base import RegisterableSpec

logger = logging.getLogger(__name__)

# Argument completion types
ARG_AGENT = "agent"
ARG_ROLE = "role"
ARG_DOMAIN = "domain"

# Source identifiers for command registration
SRC_DEFAULT = "default"
SRC_SYSTEM = "system"
SRC_OVERRIDE = "override"


@dataclass
class CommandDef:
    """Internal command definition."""
    name: str = ""
    help: str = ""
    category: str = "other"
    aliases: list[str] = field(default_factory=list)
    args: list[dict] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    system: bool = False          # True = protected, cannot be removed/modified
    handler: Callable | None = None
    source: str = SRC_DEFAULT       # SRC_DEFAULT | "yaml" | "api" | "config"


class CommandRegistry:
    """Unified command registry — system (protected) + user (mutable).

    Thread-safe via RLock.  Merges metadata from:
      1. config/commands.yaml (_defaults)
      2. praxis.yaml commands: (_overrides)
      3. Runtime API calls (_user_defs + _user_handlers)
    """

    def __init__(self):
        self._lock = __import__("threading").RLock()
        # System commands — registered by code, protected
        self._system_handlers: dict[str, Callable] = {}
        self._system_defs: dict[str, CommandDef] = {}
        # User commands — registered via API/config, mutable
        self._user_handlers: dict[str, Callable] = {}
        self._user_defs: dict[str, CommandDef] = {}
        # Metadata layers (loaded from YAML, overlaid in order)
        self._defaults: dict[str, dict] = {}      # from commands.yaml
        self._overrides: dict[str, dict] = {}     # from praxis.yaml
        self._loaded = False
        self._revision = 0  # bumped on every mutation; consumers derive indexes from it

    # ── Metadata loading ────────────────────────────────────────

    def load_defaults(self, yaml_path: str = "") -> int:
        """Load command metadata from commands.yaml."""
        path = yaml_path or _default_yaml_path()
        if not os.path.exists(path):
            logger.warning("commands.yaml not found at %s", path)
            return 0
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                self._defaults.update(data)
                self._loaded = True
                self._revision += 1
                logger.info("command_defs: loaded %d from %s", len(data), path)
                return len(data)
        except Exception as e:
            logger.warning("command_defs load failed: %s", e)
        return 0

    def load_overrides(self, cfg: dict) -> None:
        """Load command overrides from praxis.yaml commands: section."""
        if not cfg:
            return
        self._overrides.update(cfg)
        self._revision += 1
        logger.info("command overrides: %d keys", len(cfg))

    # ── Registration ────────────────────────────────────────────

    def register_system(self, name: str, handler: Callable,
                        metadata: dict | None = None) -> None:
        """Register a system command (protected from deletion/modification).

        Args:
          name: Command name (without leading /).
          handler: Callable[[list[str]], dict].
          metadata: Optional dict with help, category, aliases, args, examples.
        """
        with self._lock:
            if name in self._system_handlers:
                logger.warning("system command %s already registered — overwriting", name)
            self._system_handlers[name] = handler
            meta = metadata or self._defaults.get(name, {})
            self._system_defs[name] = CommandDef(
                name=name,
                help=meta.get("help", ""),
                category=meta.get("category", "other"),
                aliases=meta.get("aliases", []),
                args=meta.get("args", []),
                examples=meta.get("examples", []),
                system=True,
                handler=handler,
                source=SRC_SYSTEM,
            )
            self._revision += 1

    def register_user(self, name: str, handler: Callable,
                      metadata: dict) -> dict:
        """Register a user (custom) command.  Can be unregistered later.

        Args:
          name: Command name (without leading /).
          handler: Callable[[list[str]], dict].
          metadata: Dict with at minimum "help" text.
        """
        with self._lock:
            if name in self._system_handlers:
                return {"success": False, "error": f"cannot override system command: {name}"}
            if not metadata.get("help"):
                return {"success": False, "error": "metadata must include 'help'"}
            self._user_handlers[name] = handler
            self._user_defs[name] = CommandDef(
                name=name,
                help=metadata.get("help", ""),
                category=metadata.get("category", "custom"),
                aliases=metadata.get("aliases", []),
                args=metadata.get("args", []),
                examples=metadata.get("examples", []),
                system=False,
                handler=handler,
                source="api",
            )
            self._revision += 1
            return {"success": True, "name": name}

    def unregister(self, name: str) -> dict:
        """Unregister a user command.  System commands cannot be unregistered."""
        with self._lock:
            if name in self._system_handlers:
                return {"success": False, "error": f"cannot unregister system command: {name}"}
            self._user_handlers.pop(name, None)
            self._user_defs.pop(name, None)
            self._revision += 1
            return {"success": True, "name": name}

    # ── Query ───────────────────────────────────────────────────

    def get(self, name: str) -> CommandDef | None:
        """Get a merged command definition."""
        with self._lock:
            # Check user commands first (highest priority)
            if name in self._user_defs:
                return self._user_defs[name]
            # Check system commands
            if name in self._system_defs:
                return self._system_defs[name]
            # Check metadata-only (no handler registered — e.g. from commands.yaml)
            base = dict(self._defaults.get(name, {}))
            ov = self._overrides.get(name, {})
            merged = {**base, **ov}
            if ov.get("aliases"):
                merged["aliases"] = ov["aliases"]
            if ov.get("args"):
                merged["args"] = ov["args"]
            if merged.get("help"):
                return CommandDef(
                    name=name,
                    help=merged.get("help", ""),
                    category=merged.get("category", "other"),
                    aliases=merged.get("aliases", []),
                    args=merged.get("args", []),
                    examples=merged.get("examples", []),
                    system=False,
                    source=SRC_OVERRIDE if name in self._overrides else SRC_DEFAULT,
                )
            return None

    def get_handler(self, name: str) -> Callable | None:
        """Get handler function by command name."""
        with self._lock:
            if name in self._user_handlers:
                return self._user_handlers[name]
            return self._system_handlers.get(name)

    def list(self, category: str = "") -> list[dict]:
        """List all registered commands (system + user)."""
        with self._lock:
            result = []
            seen = set()

            # System commands
            for name, cd in self._system_defs.items():
                if category and cd.category != category:
                    continue
                result.append(self._to_list_item(cd))
                seen.add(name)

            # User commands
            for name, cd in self._user_defs.items():
                if name in seen:
                    continue
                if category and cd.category != category:
                    continue
                result.append(self._to_list_item(cd))
                seen.add(name)

            # Metadata-only commands that have handlers in _defaults (YAML-defined)
            for name in self._defaults:
                if name in seen:
                    continue
                if category and self._defaults[name].get("category") != category:
                    continue
                if name in self._system_handlers or name in self._user_handlers:
                    continue
                cmd = self.get(name)
                if cmd and cmd.help:
                    result.append(self._to_list_item(cmd))
                    seen.add(name)

            return sorted(result, key=lambda x: (x.get("category", ""), x["name"]))

    def has_command(self, name: str) -> bool:
        """Check if a command exists (has both metadata and handler)."""
        cmd = self.get(name)
        if cmd is None:
            return False
        return cmd.handler is not None or self.get_handler(name) is not None

    def revision(self) -> int:
        """Return the registry revision, bumped on every mutation.

        Consumers (L2 alias index, command-name caches) compare this value to
        decide whether their derived indexes are stale.
        """
        with self._lock:
            return self._revision

    def is_system(self, name: str) -> bool:
        """Check if a command is a protected system command."""
        with self._lock:
            return name in self._system_handlers

    # ── Stats ───────────────────────────────────────────────────

    def stats(self) -> dict:
        with self._lock:
            return {
                "system": len(self._system_handlers),
                "user": len(self._user_handlers),
                "metadata_defaults": len(self._defaults),
                "metadata_overrides": len(self._overrides),
            }

    # ── Internal ────────────────────────────────────────────────

    @staticmethod
    def _to_list_item(cd: CommandDef) -> dict:
        return {
            "name": cd.name,
            "help": cd.help,
            "category": cd.category,
            "aliases": cd.aliases,
            "system": cd.system,
            "source": cd.source,
            "args": [{"name": a.get("name", ""), "optional": a.get("optional", False)}
                     for a in cd.args],
            "examples": cd.examples[:3],
        }


# ── Singleton ────────────────────────────────────────────────

_REGISTRY: CommandRegistry | None = None
_REGISTRY_LOCK = __import__("threading").Lock()


def get_registry() -> CommandRegistry:
    """Get the command registry singleton."""
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = CommandRegistry()
    return _REGISTRY


def reset_registry() -> None:
    global _REGISTRY
    _REGISTRY = None


# ── Backward-compatible aliases ─────────────────────────────

def load_command_defs(yaml_path: str = "") -> int:
    return get_registry().load_defaults(yaml_path)


# ── Registry protocol helpers ──


def register_command_spec(spec: RegisterableSpec) -> bool:
    """Register a command via the unified Registry protocol."""
    return get_registry().register(spec)


def list_command_specs(category: str = "") -> list[RegisterableSpec]:
    """List commands via the unified Registry protocol."""
    return get_registry().list(category=category)


def load_command_overrides(cfg: dict) -> None:
    get_registry().load_overrides(cfg)


def register_command(name: str, handler: Callable,
                     metadata: dict | None = None) -> None:
    get_registry().register_system(name, handler, metadata)


def get_command(name: str) -> dict | None:
    """Look up a registered command by name."""
    cd = get_registry().get(name)
    if cd is None:
        return None
    return {
        "name": cd.name,
        "help": cd.help,
        "category": cd.category,
        "aliases": cd.aliases,
        "args": cd.args,
        "examples": cd.examples,
        "has_handler": cd.handler is not None or get_registry().get_handler(name) is not None,
    }


def get_handler(name: str) -> Callable | None:
    """Get a registered command handler by name (or None)."""
    return get_registry().get_handler(name)


def list_commands() -> list[dict]:
    """List registered system commands."""
    return [{
        "name": c["name"],
        "help": c["help"],
        "aliases": c["aliases"],
        "category": c["category"],
        "examples": c.get("examples", []),
        "args": c.get("args", []),
    } for c in get_registry().list()]


def list_all_definitions() -> dict:
    reg = get_registry()
    return {
        "system": {n: {"help": cd.help, "category": cd.category}
                    for n, cd in reg._system_defs.items()},
        "user": {n: {"help": cd.help, "category": cd.category}
                  for n, cd in reg._user_defs.items()},
        "metadata": dict(reg._defaults),
        "overrides": dict(reg._overrides),
    }


def _default_yaml_path() -> str:
    from l1.kernel.params.system import COMMANDS_CONFIG_PATH
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        COMMANDS_CONFIG_PATH,
    )
