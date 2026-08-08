"""PraxisPaths — platform-aware path resolution for all deployment modes.

Architecture:
  DeployMode detection (auto / env override)
    └─ PraxisPaths.dataclass (all paths in one place)
         ├─ data_dir          — root for all data files
         ├─ config_dir        — config file directory
         ├─ config_file       — praxis.yaml path
         ├─ constitution_file — .praxis-rules.md path
         ├─ skill_dirs        — skill discovery paths (list, prioritized)
         ├─ skill_evolved_dir — evolved skills write target
         ├─ skill_lean_dir    — lean case storage
         ├─ memories_dir      — agent memory persistence
         └─ ... (all derived paths)

Usage:
  from l1.kernel.paths import get_paths
  paths = get_paths()  # singleton, auto-detects deploy mode
  paths.data_dir       # → "/home/user/.praxis/"
  paths.skill_dirs     # → ["/home/user/.praxis/skills", ".praxis/skills"]
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Self

from .platform import IS_MAC, IS_WINDOWS

logger = logging.getLogger(__name__)


class DeployMode(Enum):
    """Detected or configured deployment mode — determines all path defaults."""

    CLI_PROJECT = "cli"  # Local project (default)
    PIP_PACKAGE = "pip"  # pip install
    IDE_PLUGIN = "ide"  # VSCode / JetBrains plugin
    DESKTOP_MAC = "desktop_mac"  # macOS desktop app
    DESKTOP_WIN = "desktop_win"  # Windows desktop app
    DOCKER = "docker"  # Container
    BINARY = "binary"  # PyInstaller / Nuitka bundled


def _detect_deploy_mode() -> DeployMode:
    """Auto-detect deployment mode based on runtime environment."""
    mode_str = os.environ.get("PRAXIS_DEPLOY_MODE", "").lower()
    if mode_str:
        try:
            return DeployMode(mode_str)
        except ValueError:
            logger.debug("paths: unknown PRAXIS_DEPLOY_MODE=%r, falling back to auto-detect", mode_str)

    if os.path.exists("/.dockerenv") or os.environ.get("DOCKER") == "1":
        return DeployMode.DOCKER

    if getattr(sys, "frozen", False):
        return DeployMode.BINARY

    if os.environ.get("PRAXIS_IDE_MODE"):
        return DeployMode.IDE_PLUGIN

    try:
        import l1.kernel as _mod

        _pkg = Path(_mod.__file__).resolve().parent.parent.parent.parent
        if "site-packages" in str(_pkg):
            return DeployMode.PIP_PACKAGE
    except Exception:
        logger.debug("paths: PIP_PACKAGE detection failed", exc_info=True)

    return DeployMode.CLI_PROJECT


def _get_data_dir(mode: DeployMode) -> str:
    """Return the default data root directory for given deploy mode."""
    env_val = os.environ.get("PRAXIS_DATA_DIR")
    if env_val:
        return env_val

    home = Path.home()
    if IS_WINDOWS:
        user_data_dir = Path(os.environ.get("APPDATA", str(home))) / "praxis"
    elif IS_MAC:
        user_data_dir = home / "Library" / "Application Support" / "praxis"
    else:
        user_data_dir = home / ".local" / "share" / "praxis"

    base: dict[DeployMode, str] = {
        DeployMode.CLI_PROJECT: ".praxis",
        DeployMode.PIP_PACKAGE: str(user_data_dir),
        DeployMode.IDE_PLUGIN: str(user_data_dir),
        DeployMode.DESKTOP_MAC: str(home / "Library" / "Application Support" / "praxis"),
        DeployMode.DESKTOP_WIN: str(Path(os.environ.get("APPDATA", str(home))) / "praxis"),
        DeployMode.DOCKER: "/var/praxis",
        DeployMode.BINARY: str(home / ".praxis"),
    }
    return base.get(mode, ".praxis")


def _get_config_dir(mode: DeployMode) -> str:
    """Return config directory for given mode."""
    env_val = os.environ.get("PRAXIS_CONFIG_DIR")
    if env_val:
        return env_val
    if mode == DeployMode.CLI_PROJECT:
        return ".config/praxis"
    return _get_data_dir(mode)


def _get_skill_dirs(mode: DeployMode, data_dir: str) -> list[str]:
    """Return skill discovery paths, highest priority first."""
    env_val = os.environ.get("PRAXIS_SKILL_DIR")
    if env_val:
        # Env override points at an isolated runtime dir (e.g. xdist worker
        # isolation in tests) — keep the repo's built-in read-only skills on
        # the discovery path so builtins still load, just behind the override.
        return [env_val, "config/skills"]

    base: dict[DeployMode, list[str]] = {
        DeployMode.CLI_PROJECT: [
            "config/skills",  # built-in skills — shipped with the repo (read-only)
            ".praxis/skills",  # runtime skill store (evolved/lean/user)
            "skills",
            "skills/evolved",  # project-scoped evolved skills (round-trip with skill_project_evolved_dir)
            ".skills",
        ],
        DeployMode.PIP_PACKAGE: [
            os.path.join(data_dir, "skills"),
            (
                lambda _pkg: (
                    os.path.join(os.path.dirname(_pkg.__file__), "..", "..", "skills")
                    if _pkg is not None and _pkg.__file__
                    else ""
                )
            )(sys.modules.get("l1.kernel")),
        ],
        DeployMode.IDE_PLUGIN: [
            os.path.join(data_dir, "skills"),
        ],
        DeployMode.DESKTOP_MAC: [
            os.path.join(data_dir, "skills"),
        ],
        DeployMode.DESKTOP_WIN: [
            os.path.join(data_dir, "skills"),
        ],
        DeployMode.DOCKER: [
            "/etc/praxis/skills",
            os.path.join(data_dir, "skills"),
        ],
        DeployMode.BINARY: [
            os.path.join(os.path.dirname(sys.executable), "skills") if getattr(sys, "frozen", False) else "",
            os.path.join(data_dir, "skills"),
        ],
    }
    dirs = base.get(mode, [])
    return [d for d in dirs if d]


@dataclass
class PraxisPaths:
    """All Praxis runtime paths — single source of truth.

    Instantiated once via detect() or from_env().  Consumers call
    get_paths() to access the singleton, then read attribute.
    """

    # ── Identity ──
    deploy_mode: DeployMode = DeployMode.CLI_PROJECT

    # ── Root directories ──
    data_dir: str = ""
    config_dir: str = ""

    # ── Config files ──
    config_file: str = ""
    constitution_file: str = ".praxis-rules.md"
    settings_file: str = ".praxis_settings.json"

    # ── Skill system ──
    skill_dirs: list[str] = field(default_factory=list)
    skill_evolved_dir: str = ""
    skill_lean_dir: str = ""
    # Project-scoped evolution target — evolved skills that should travel with
    # the project (e.g. into VCS) land here; global ones go to skill_evolved_dir.
    skill_project_evolved_dir: str = ""
    # Where evolved skills are written: "project" (default, CLI_PROJECT) | "global".
    skill_scope: str = "project"

    # ── Memories / persistence ──
    memories_dir: str = ""
    events_db: str = ""
    state_json: str = ""

    # ── Cell state ──
    cell_state_template: str = "cell_{}.json"

    # ── Card registry / gates ──
    card_registry: str = ""
    card_gate: str = ""
    pending_queue: str = ""
    issue_table: str = ""
    approval_gate: str = ""
    capability_gate: str = ""

    # ── Serialized state files ──
    mute_state: str = ""
    mode_state: str = ""
    todo_state: str = ""
    sandbox_state: str = ""
    todo_table: str = ""
    todo_dir: str = ""
    transaction_area: str = ""
    statecharts: str = ""
    execution_results: str = ""
    dialogue_session: str = ""
    message_gate_state: str = ""
    vault_salt: str = ""
    chain_key: str = ""
    archive_db: str = ""
    mcp_state: str = ""

    # ── Monitor / records ──
    seq_monitor_template: str = "seq_monitor_{}.json"
    monitor_bus_log: str = ""

    # ── Sandbox ──
    sandbox_root: str = ""

    # ── IPC sockets ──
    socket_dir: str = ""

    # ── Templates ──
    memory_persist_ring2: str = "memory_ring2.jsonl"
    memory_persist_ring3: str = "memory_ring3.db"
    sandbox_state_template: str = "{cell_id}.state.json"
    snapshot_path_template: str = "{snapshot_id}.snapshot.json"
    skill_lean_case_template: str = "{agent_id}_{tool_name}_{ts}.json"
    agent_session_template: str = "{ts}_{prefix}.json"

    # ── Boot ──
    vfs_temp_path: str = "/tmp"

    def __post_init__(self) -> None:
        """Derive all child paths from root directories."""
        if not self.data_dir:
            self.data_dir = _get_data_dir(self.deploy_mode)
        if not self.config_dir:
            self.config_dir = _get_config_dir(self.deploy_mode)
        if not self.config_file:
            if self.deploy_mode == DeployMode.CLI_PROJECT:
                self.config_file = "config/praxis.yaml"
            else:
                self.config_file = os.path.join(self.config_dir, "praxis.yaml")
        if not self.skill_dirs:
            self.skill_dirs = _get_skill_dirs(self.deploy_mode, self.data_dir)
        if not self.skill_evolved_dir:
            self.skill_evolved_dir = os.path.join(self.data_dir, "skills", "evolved")
        if not self.skill_project_evolved_dir:
            if self.deploy_mode == DeployMode.CLI_PROJECT:
                # Project-scoped evolution travels with the repo — resolve from
                # the package root (paths.py is in src/l1/kernel) so it matches
                # the discovery base used by SkillManager.load_builtin()
                # (kernel_dir/../../..), not the ephemeral os.getcwd().
                kernel_dir = os.path.dirname(os.path.abspath(__file__))
                self.skill_project_evolved_dir = os.path.join(kernel_dir, "..", "..", "..", "skills", "evolved")
            else:
                self.skill_project_evolved_dir = self.skill_evolved_dir
        if not self.skill_lean_dir:
            self.skill_lean_dir = os.path.join(self.data_dir, "skills", "lean")
        if not self.memories_dir:
            self.memories_dir = os.path.join(self.data_dir, "memories")

        dd = self.data_dir
        self.events_db = os.path.join(dd, "events.db")
        self.state_json = os.path.join(dd, "state.json")
        self.card_registry = os.path.join(dd, "card_registry.json")
        self.card_gate = os.path.join(dd, "card_gate.json")
        self.pending_queue = os.path.join(dd, "pending_queue.json")
        self.issue_table = os.path.join(dd, "issue_table.json")
        self.approval_gate = os.path.join(dd, "approval_gate.json")
        self.capability_gate = os.path.join(dd, "capability_gate.json")
        self.mute_state = os.path.join(dd, "mute_state.json")
        self.mode_state = os.path.join(dd, "mode.json")
        self.todo_state = os.path.join(dd, "todo_state.json")
        self.sandbox_state = os.path.join(dd, "sandbox_state.json")
        self.todo_table = os.path.join(dd, "todo_table.json")
        self.todo_dir = os.path.join(dd, "todos")
        self.transaction_area = os.path.join(dd, "transaction_area.json")
        self.statecharts = os.path.join(dd, "statecharts.json")
        self.execution_results = os.path.join(dd, "execution_results.json")
        self.dialogue_session = os.path.join(dd, "dialogue_session.json")
        self.message_gate_state = os.path.join(dd, "message_gate.json")
        self.vault_salt = os.path.join(dd, ".praxis_vault_salt")
        self.chain_key = os.path.join(dd, ".chain_key")
        self.archive_db = os.path.join(dd, "archive.db")
        self.mcp_state = os.path.join(dd, "mcp_state.json")
        self.monitor_bus_log = os.path.join(dd, "monitor_bus.jsonl")
        self.sandbox_root = os.path.join(dd, "sandbox")
        self.socket_dir = os.path.join(dd, "sockets")
        self.cell_state_template = os.path.join(dd, "cell_{}.json")
        self.seq_monitor_template = os.path.join(dd, "seq_monitor_{}.json")

    @classmethod
    def detect(cls) -> Self:
        """Auto-detect deployment mode and build path set."""
        mode = _detect_deploy_mode()
        return cls(deploy_mode=mode)

    @classmethod
    def from_env(cls) -> Self:
        """Build from environment overrides with auto-detect fallback."""
        mode_str = os.environ.get("PRAXIS_DEPLOY_MODE", "")
        mode = DeployMode(mode_str) if mode_str else _detect_deploy_mode()
        return cls(deploy_mode=mode)

    def to_dict(self) -> dict:
        """Export all paths as flat dict (for debugging / API)."""
        return {k: str(v) for k, v in self.__dict__.items() if not k.startswith("_") and isinstance(v, (str, list))}


# ── Singleton ──

_paths: PraxisPaths | None = None
_paths_lock = threading.Lock()


def get_paths() -> PraxisPaths:
    """Get or create the PraxisPaths singleton."""
    global _paths
    if _paths is None:
        with _paths_lock:
            if _paths is None:
                _paths = PraxisPaths.detect()
    return _paths


def reset_paths() -> None:
    """Reset the singleton (useful for tests)."""
    global _paths
    _paths = None


def configure_paths(
    deploy_mode: str | None = None,
    data_dir: str | None = None,
    config_file: str | None = None,
    skill_dirs: list[str] | None = None,
) -> PraxisPaths:
    """Explicitly configure paths (called by boot after loading praxis.yaml)."""
    global _paths
    mode = DeployMode(deploy_mode) if deploy_mode else _detect_deploy_mode()
    _paths = PraxisPaths(deploy_mode=mode)
    if data_dir:
        _paths.data_dir = data_dir
        # Re-derive children
        _paths.__post_init__()
    if config_file:
        _paths.config_file = config_file
    if skill_dirs is not None:
        _paths.skill_dirs = skill_dirs
    return _paths


# ── Backward-compatible accessors ──


def data_dir() -> str:
    return get_paths().data_dir


def config_dir() -> str:
    return get_paths().config_dir


def skill_evolved_dir() -> str:
    return get_paths().skill_evolved_dir


def skill_project_evolved_dir() -> str:
    return get_paths().skill_project_evolved_dir


def skill_lean_dir() -> str:
    return get_paths().skill_lean_dir


def memories_dir() -> str:
    return get_paths().memories_dir


def events_db() -> str:
    return get_paths().events_db


def monitor_bus_log() -> str:
    return get_paths().monitor_bus_log
