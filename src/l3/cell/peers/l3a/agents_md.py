"""L3A agents-md pipeline — generate a project handbook (AGENTS.md) for any project.

Decision layer entry point: an L3A session (or L2 ``/agents-md``) triggers
collection of structural facts about the current project (layers, commands,
params constants, key paths), assembles them into an agent-facing handbook,
writes it through the Cell sandbox, and optionally distills reusable rules
back into the skill system (global scope) via the R4Agent.

The collector below is pure filesystem scanning — no LLM, no sandbox, no L4
imports — so it stays safe under the layer-import constraint and can run in
any process (L3A session, L2 command handler, unit test).
"""

from __future__ import annotations

import ast
import logging
import os
from pathlib import Path

from l1.kernel.params.system import HASH_TRUNC_MEDIUM, LOG_TRUNC_80

logger = logging.getLogger(__name__)

# Layer table: relative src/ dir -> display name. Mirrors scripts/gen-doc-stats.py.
_LAYER_DIRS: dict[str, str] = {
    "l1/kernel": "L1 Kernel",
    "l2": "L2 Shell",
    "l3": "L3 Cell",
    "l4": "L4 Bridge",
    "l5": "L5 User",
}

# Sub-layer table for the hotspot stats (mirrors gen-doc-stats.py).
_SUBLAYER_DIRS: dict[str, str] = {
    "l3/cell/peers/l3a": "L3A (peers)",
    "l3/memory": "L3 Memory",
    "l3/card": "L3 Card",
    "l3/services": "L3 Services",
    "l3/bus": "L3 Bus",
    "l3/agent": "L3 Agent",
    "l4/api_handlers": "L4 Handlers",
}

# Project-structure paths probed for the handbook's key-files section.
_KEY_PATHS: list[str] = [
    "config/praxis.yaml",
    "config/commands.yaml",
    "config/tools.yaml",
    ".praxis-rules.md",
    "locales/",
    "memories/",
    "config/skills/",
    ".praxis/skills/",
]


def _py_files(root: Path) -> list[Path]:
    """Return all .py files under root, skipping __pycache__."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in str(p))


def _count_lines(files: list[Path]) -> int:
    """Count total lines across files (best-effort, skips undecodable files)."""
    total = 0
    for p in files:
        try:
            total += sum(1 for _ in p.open(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return total


def _dir_stats(root: Path, rel: str) -> dict:
    """Return {"files": N, "lines": N} for src/<rel>, or zeroed dict when absent."""
    files = _py_files(root / rel)
    return {"files": len(files), "lines": _count_lines(files)}


def _count_params_constants(params_dir: Path) -> int:
    """Count module-level uppercase annotated constants via AST (gen-doc-stats style)."""
    consts = 0
    for p in _py_files(params_dir):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id.isupper():
                consts += 1
    return consts


def _find_project_root(start: str = "") -> str:
    """Locate the project root: the nearest ancestor of start holding src/.

    Falls back to start (or cwd) when no src/ ancestor is found, so the
    collector degrades gracefully outside a source checkout.
    """
    cur = Path(start or os.getcwd()).resolve()
    for _ in range(6):
        if (cur / "src").is_dir():
            return str(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    return str(Path(start or os.getcwd()).resolve())


def collect_project_info(project_root: str = "") -> dict:
    """Collect structural facts about a project for handbook generation.

    Args:
        project_root: Explicit project root; empty means auto-discover by
            walking up from cwd until a ``src/`` directory is found.

    Returns:
        Dict with ``project_root``, ``layers`` / ``sublayers`` (file+line
        stats per dir), ``params`` (module/constant counts), ``commands``
        (command count from commands.yaml), ``tests`` (file/line stats),
        and ``key_paths`` (existence probes). Pure filesystem scan, never
        raises.
    """
    root = Path(project_root or _find_project_root()).resolve()
    info: dict = {
        "project_root": str(root),
        "layers": {},
        "sublayers": {},
        "params": {"modules": 0, "constants": 0},
        "commands": 0,
        "tests": {"files": 0, "lines": 0},
        "key_paths": {},
    }

    src = root / "src"
    for rel, _name in _LAYER_DIRS.items():
        info["layers"][rel] = _dir_stats(src, rel)
    for rel, _name in _SUBLAYER_DIRS.items():
        info["sublayers"][rel] = _dir_stats(src, rel)

    params_dir = src / "l1/kernel/params"
    info["params"]["modules"] = len(_py_files(params_dir))
    info["params"]["constants"] = _count_params_constants(params_dir)

    commands_yaml = root / "config" / "commands.yaml"
    if commands_yaml.is_file():
        try:
            import yaml

            data = yaml.safe_load(commands_yaml.read_text(encoding="utf-8"))
            info["commands"] = len(data) if isinstance(data, dict) else 0
        except Exception:
            logger.debug("agents_md: commands.yaml parse failed", exc_info=True)

    info["tests"] = _dir_stats(root, "tests")

    for rel in _KEY_PATHS:
        info["key_paths"][rel] = (root / rel).exists()

    return info


def assemble_agents_md(info: dict) -> str:
    """Assemble an AGENTS.md handbook from collected project facts.

    Produces a structural skeleton: title, quick-start placeholders,
    architecture tree with per-layer file/line stats, key numbers
    (params constants, commands, tests), key-path probes, and a
    conventions section left for LLM/human refinement. Every fact comes
    from ``collect_project_info`` — never invented.
    """
    name = Path(info["project_root"]).name
    lines = [
        f"# {name} — Agent Handbook",
        "",
        "> Generated by the Praxis L3A agents-md pipeline (agent-facing).",
        "> Regenerate: `/agents-md generate` — facts below are live-scanned.",
        "",
        "## Quick start",
        "",
        "- *TODO: install, build, and run commands (verify against the repo).*",
        "",
        "## Test commands",
        "",
        "- *TODO: exact test/lint/format commands (verify before asserting).*",
        "",
        "## Architecture",
        "",
    ]
    for rel, disp in _LAYER_DIRS.items():
        st = info["layers"].get(rel, {"files": 0, "lines": 0})
        lines.append(f"- {rel}/ — {disp}: {st['files']} files, {st['lines']} lines")
    lines.append("")
    lines.append("### Hotspots")
    lines.append("")
    for rel, disp in _SUBLAYER_DIRS.items():
        st = info["sublayers"].get(rel, {"files": 0, "lines": 0})
        lines.append(f"- {rel}/ — {disp}: {st['files']} files, {st['lines']} lines")
    lines.append("")
    lines.append("## Key numbers (live-scanned)")
    lines.append("")
    lines.append(f"- Params constants: {info['params']['constants']} across {info['params']['modules']} modules")
    lines.append(f"- L2 shell commands: {info['commands']}")
    lines.append(f"- Tests: {info['tests']['files']} files, {info['tests']['lines']} lines")
    lines.append("")
    lines.append("## Key files / paths")
    lines.append("")
    for rel, exists in info["key_paths"].items():
        lines.append(f"- `{rel}` — {'present' if exists else 'absent'}")
    lines.append("")
    lines.append("## Conventions")
    lines.append("")
    lines.append("- *TODO: code style, commit rules, and gotchas (LLM/human pass).*")
    lines.append("")
    return "\n".join(lines)


def write_agents_md(content: str, agent_id: str = "l3a", cell_id: str = "", project_root: str = "") -> dict:
    """Write the assembled handbook to ``<project_root>/AGENTS.md`` via the sandbox.

    All modifications go through the sandbox (constitution §4.5): the write
    is staged with per-hunk attribution, then flushed into the project.
    When no ``cell_id`` is given, a throwaway ``agents-md`` sandbox cell is
    created for the project root.

    Returns the flush result dict (``success`` + sandbox details).
    """
    from l4.sandbox import get_manager

    mgr = get_manager()
    cid = cell_id or "agents-md"
    sb = mgr.get_cell(cid)
    if sb is None:
        mgr.create_cell(cid, project_root or _find_project_root())
        sb = mgr.get_cell(cid)
    if sb is None:
        return {"success": False, "error": "sandbox cell unavailable"}
    r = sb.write("AGENTS.md", content, agent_id, task_id="agents-md", tool_name="agents_md")
    if not r.get("success"):
        return r
    # write() stages a "pending" entry; flush() only copies "staged" ones,
    # so promote the entry before flushing (sandbox write→stage→flush chain).
    st = sb.stage(agent_id)
    if not st.get("success"):
        return st
    return sb.flush(agent_id, ["AGENTS.md"])


def _fallback_generic_skill(intent: str, scope: str = "global") -> dict:
    """Register a rule-based template skill when the LLM engine is unavailable.

    Keeps the generic-handbook pipeline functional without an LLM: the skill
    carries the writing-for-agents essence (explore → verify → write in
    place) plus the caller's intent as a versioned prompt, persisted with
    the same round-trip frontmatter as LLM-evolved skills.
    """
    import hashlib
    import time

    from l1.kernel.skill import get_skill_manager
    from l3.memory.r4_agent import get_r4_agent

    fp = hashlib.md5(intent.encode("utf-8")).hexdigest()[:HASH_TRUNC_MEDIUM]
    name = f"agents-md-{int(time.time())}"
    description = f"Generic project-handbook generation ({intent[:LOG_TRUNC_80]}) [{fp}]"
    prompt = (
        "Generate or refresh the project handbook (AGENTS.md). Explore the "
        "codebase first (build/test/lint commands, layout, conventions, "
        "gotchas), verify every count/path/command against the code, then "
        "write in place preserving existing useful content. Intent: "
        f"{intent.strip()}"
    )
    r4 = get_r4_agent()
    sm = get_skill_manager()
    r = sm.create(
        name=name,
        description=description,
        prompt=prompt,
        tags=["agents-md", "evolved"],
        allowed_tools=["read_file", "list_dir", "write_file", "grep_search"],
        internal=True,
    )
    if not r.get("success"):
        return r
    r4._persist_skill_md(
        name=name,
        description=description,
        prompt=prompt,
        tags=["agents-md", "evolved"],
        allowed_tools=["read_file", "list_dir", "write_file", "grep_search"],
        scope=scope,
    )
    return {"success": True, "skill": name, "scope": scope, "fallback": True}


def evolve_generic_skill(intent: str, cell_id: str = "", scope: str = "global") -> dict:
    """Distill a reusable, project-agnostic skill from the handbook pipeline.

    Delegates to ``R4Agent.evolve_skill`` (LLM skill architect) with an
    explicit global scope so the evolved skill travels with the machine and
    applies to any project; when the LLM is unavailable, falls back to a
    rule-based template skill so the generic end of the pipeline still
    completes. Returns the evolution result dict.
    """
    from l3.memory.r4_agent import get_r4_agent

    r4 = get_r4_agent()
    r = r4.evolve_skill(intent, cell_id=cell_id, scope=scope)
    if r.get("success"):
        return r
    logger.info("agents_md: LLM evolve_skill unavailable (%s), using fallback", r.get("error", "?"))
    return _fallback_generic_skill(intent, scope=scope)


def generate_agents_md(agent_id: str = "l3a", cell_id: str = "", project_root: str = "", evolve: bool = True) -> dict:
    """Full pipeline: collect → assemble → sandbox write → (optional) generalize.

    Runs the generic handbook pipeline for any project. When ``evolve`` is
    true, also distills a reusable skill via ``evolve_generic_skill`` so the
    method survives beyond this project. Returns a summary dict.
    """
    info = collect_project_info(project_root)
    md = assemble_agents_md(info)
    w = write_agents_md(md, agent_id=agent_id, cell_id=cell_id, project_root=info["project_root"])
    result: dict = {"success": bool(w.get("success")), "write": w}
    if not w.get("success"):
        result["error"] = w.get("error", "sandbox write failed")
        return result
    result["stats"] = {
        "project_root": info["project_root"],
        "commands": info["commands"],
        "params_constants": info["params"]["constants"],
        "tests_files": info["tests"]["files"],
        "layers": {k: v["files"] for k, v in info["layers"].items()},
    }
    if evolve:
        intent = (
            "Generate or refresh the project handbook (AGENTS.md) for any "
            "project: explore build/test/lint commands, directory layout, "
            "conventions and gotchas; verify every count/path against the "
            "code; write in place preserving existing useful content."
        )
        result["evolved"] = evolve_generic_skill(intent, cell_id=cell_id)
    return result
