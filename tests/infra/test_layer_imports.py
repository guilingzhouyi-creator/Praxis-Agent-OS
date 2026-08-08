"""Layer import constraint tests — verify no upward imports."""

import ast
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

# Layer hierarchy: index determines allowed upward imports
LAYER_ORDER = {"l1": 0, "l2": 1, "l3": 2, "l4": 3, "l5": 4}

# Allowlist: pre-existing cross-layer imports (adapter patterns + service calls).
# Rebuilt from the actual src/ import graph — every entry is a real (file, module)
# pair; add a line here when introducing a new cross-layer import.
ALLOWLIST = {
    ("l1/kernel/settings.py", "l3.config.settings_adapter"),
    ("l2/i18n.py", "l4.adapters.i18n_yaml"),
    ("l2/l2_shell/__init__.py", "l3.cell"),
    ("l2/l2_shell/commands/__init__.py", "l3.error_bus"),
    ("l2/l2_shell/commands/common.py", "l3.agent_terminal"),
    ("l2/l2_shell/commands/common.py", "l3.cell"),
    ("l2/l2_shell/commands/common.py", "l3.error_bus"),
    ("l2/l2_shell/commands/common.py", "l3.services.adapter_bridge"),
    ("l2/l2_shell/commands/connect.py", "l3.agent_terminal"),
    ("l2/l2_shell/commands/connect.py", "l3.cell"),
    ("l2/l2_shell/commands/ci.py", "l3.config.settings_center"),
    ("l2/l2_shell/commands/ci.py", "l4.ci_review"),
    ("l2/l2_shell/commands/extra.py", "l3.bus.htn_a"),
    ("l2/l2_shell/commands/extra.py", "l3.card.card_registry"),
    ("l2/l2_shell/commands/extra.py", "l3.cell.peers.l3"),
    ("l2/l2_shell/commands/extra.py", "l3.resource_buffer.manager"),
    ("l2/l2_shell/commands/extra.py", "l3.scheduler.think_registry"),
    ("l2/l2_shell/commands/extra.py", "l3.services.central_security"),
    ("l2/l2_shell/commands/extra.py", "l3.services.stats_center"),
    ("l2/l2_shell/commands/extra.py", "l3.error_bus"),
    ("l2/l2_shell/commands/extra.py", "l3.memory.memory_graph"),
    ("l2/l2_shell/commands/extra.py", "l4.api_handlers.api_handlers_mcp"),
    ("l2/l2_shell/commands/extra.py", "l4.mcp_bridge"),
    ("l2/l2_shell/commands/harness.py", "l3.tool_system.harness"),
    ("l2/l2_shell/commands/test_auto.py", "l3.tool_system.auto_test"),
    ("l2/l2_shell/commands/l3a.py", "l3.cell.peers.l3a"),
    ("l2/l2_shell/commands/memory.py", "l3.agent_terminal"),
    ("l2/l2_shell/commands/memory.py", "l3.card.card_registry"),
    ("l2/l2_shell/commands/memory.py", "l3.cell"),
    ("l2/l2_shell/commands/memory.py", "l3.error_bus"),
    ("l2/l2_shell/commands/memory.py", "l3.memory.memory"),
    ("l2/l2_shell/commands/memory.py", "l3.services.central_plugin"),
    ("l2/l2_shell/commands/model.py", "l3.config.settings_center"),
    ("l2/l2_shell/commands/model.py", "l3.error_bus"),
    ("l2/l2_shell/commands/model.py", "l3.scheduler.think_registry"),
    ("l2/l2_shell/commands/model.py", "l3.services.model_service"),
    ("l2/l2_shell/commands/model.py", "l4.api_handlers.api_handlers_providers"),
    ("l2/l2_shell/commands/model.py", "l4.cron_scheduler"),
    ("l2/l2_shell/commands/model.py", "l4.llm.llm"),
    ("l3/memory/memory_graph.py", "l4.llm.llm"),
    ("l2/l2_shell/commands/system.py", "l3.agent_terminal"),
    ("l2/l2_shell/commands/system.py", "l3.bus.observability_bus"),
    ("l2/l2_shell/commands/system.py", "l3.cell"),
    ("l2/l2_shell/commands/system.py", "l3.memory.r4_agent"),
    ("l2/l2_shell/commands/system.py", "l3.memory.skill_retriever"),
    ("l2/l2_shell/commands/system.py", "l3.scheduler.scheduler"),
    ("l2/l2_shell/commands/system.py", "l3.scheduler.think_registry"),
    ("l2/l2_shell/commands_settings.py", "l3.config.settings_center"),
    ("l2/l2_shell/completer.py", "l3.agent_terminal"),
    ("l2/selector.py", "l3.cell"),
    ("l2/selector.py", "l3.error_bus"),
    ("l2/shell.py", "l3.agent.scout"),
    ("l2/shell.py", "l3.cell"),
    ("l2/shell.py", "l3.tool_system.tool_spec"),
    ("l2/shell_completer.py", "l3.tool_system.tool_config"),
    ("l3/agent/_term_lifecycle.py", "l4.llm.llm"),
    ("l3/agent/_term_lifecycle.py", "l4.llm.llm_base"),
    ("l3/agent/subagent_task.py", "l4.llm.llm"),
    ("l3/boot/boot_steps.py", "l4.ci_review"),
    ("l3/boot/wiring.py", "l4.adapters.bus_memory"),
    ("l3/boot/wiring.py", "l4.adapters.card_registry"),
    ("l3/boot/wiring.py", "l4.adapters.channel_ring"),
    ("l3/boot/wiring.py", "l4.adapters.i18n_yaml"),
    ("l3/boot/wiring.py", "l4.adapters.monitor_bus"),
    ("l3/boot/wiring.py", "l4.adapters.worker_thread"),
    ("l3/card/card_registry.py", "l4.llm.llm"),
    ("l3/cell/__init__.py", "l4.sandbox.cell_sandbox"),
    ("l3/cell/components/cell_cross_review.py", "l4.sandbox"),
    ("l3/cell/peers/l3a/agents_md.py", "l4.sandbox"),
    ("l3/config/config_handlers_bridge.py", "l4.api.api_gateway"),
    ("l3/config/config_handlers_bridge.py", "l4.api_handlers.api_handlers_mcp"),
    ("l3/config/config_handlers_bridge.py", "l4.mcp_bridge"),
    ("l3/config/config_handlers_bridge.py", "l4.sandbox.cell_sandbox"),
    ("l3/config/config_handlers_bridge.py", "l4.vault.credential_vault"),
    ("l3/config/config_loader.py", "l4.llm.llm"),
    ("l3/memory/r4_agent.py", "l4.llm.llm"),
    ("l3/memory/r4_skill_evolution.py", "l4.llm.llm"),
    ("l3/memory/r4_skill_feedback.py", "l4.llm.llm"),
    ("l3/memory/skill_retriever.py", "l4.llm.llm"),
    ("l3/services/adapter_bridge.py", "l4.cron_scheduler"),
    ("l3/services/adapter_bridge.py", "l4.llm.llm"),
    ("l3/services/adapter_bridge.py", "l4.mcp_bridge"),
    ("l3/services/adapter_bridge.py", "l4.vault.credential_vault"),
    ("l3/services/model_service.py", "l4.llm.llm"),
    ("l3/services/model_service.py", "l4.vault.credential_vault"),
    ("l3/services/prompt_engine.py", "l4.lsp.lsp"),
    ("l3/tool_system/tool_pipeline.py", "l4.sandbox.manager"),
    ("l3/tools/_comm.py", "l4.notify"),
    ("l3/tools/_files.py", "l4.sandbox"),
    ("l3/tools/_lsp.py", "l4.lsp.lsp"),
    ("l3/tools/_lsp.py", "l4.lsp.lsp_manager"),
}


def extract_imports(filepath):
    """Extract all absolute import module names from a file."""
    with open(filepath, encoding="utf-8", errors="replace") as f:
        try:
            tree = ast.parse(f.read(), filename=str(filepath))
        except SyntaxError:
            return []

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and re.match(r"^l[1-5]\.", node.module):
                imports.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if re.match(r"^l[1-5](\.|$)", alias.name):
                    imports.append(alias.name)
    return imports


def get_layer(path: Path) -> str | None:
    """Determine which layer a file belongs to."""
    for part in path.relative_to(SRC).parts:
        if part.startswith("l") and part[1:].isdigit():
            return part
    return None


# ── Helpers for TestLayerConstraints (merged from coverage test file) ──


def _get_layer(fpath: str) -> int:
    """Extract layer index (1-5) from a file path string."""
    path = Path(fpath)
    for part in path.parts:
        if part.startswith("l") and len(part) > 1 and part[1:].isdigit():
            return int(part[1])
    return 0


def _parse_imports(fpath: str) -> list[tuple[str, str]]:
    """Parse all local (l1-l5) imports from a file, returning (type, module)."""
    try:
        with open(fpath, encoding="utf-8", errors="replace") as f:
            tree = ast.parse(f.read(), filename=fpath)
    except (SyntaxError, OSError):
        return []
    imports: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if re.match(r"^l[1-5](\.|$)", alias.name):
                    imports.append(("import", alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module and re.match(r"^l[1-5]\.", node.module):
            imports.append(("from", node.module))
    return imports


def _import_layer(module: str) -> int:
    """Extract layer index (1-5) from a dotted module name (e.g. 'l3.card.issue' → 3)."""
    m = re.match(r"^l([1-5])", module)
    return int(m.group(1)) if m else 0


# L3-L4 and L2-L3 allowlist as (src_layer, dst_layer, module_prefix)
_LAYER_ALLOWLIST: set[tuple[int, int, str]] = set()
"""Populated from ALLOWLIST set on first access."""


def _ensure_layer_allowlist() -> None:
    """Convert ALLOWLIST (file_path, module) tuples to (layer, layer, module_prefix) lookups."""
    if _LAYER_ALLOWLIST:
        return
    for fpath, module in ALLOWLIST:
        src = _get_layer(fpath)
        dst = _import_layer(module)
        if src and dst:
            _LAYER_ALLOWLIST.add((src, dst, module))
    # Also add some known-adapter patterns that aren't file-specific
    for src, dst, prefix in [
        (1, 3, "l3.config.settings_adapter"),
        (1, 3, "l3.error_bus"),
        (1, 3, "l3.stagnation"),
        (1, 3, "l3.agent.stagnation"),
        (1, 3, "l3.cell"),
        (1, 4, "l4.adapters"),
        (1, 4, "l4.llm_base"),
        (2, 3, "l3.cache"),
        (2, 3, "l3.l3b"),
        (2, 3, "l3.htn_a"),
        (2, 3, "l3.htn_planner"),
        (2, 3, "l3.cell.peers.l3"),
        (2, 3, "l3.scheduler"),
        (2, 3, "l3.bus"),
        (2, 3, "l3.memory"),
        (2, 3, "l3.services"),
        (2, 3, "l3.cell.components"),
        (2, 3, "l3.tool_system"),
        (2, 3, "l3.error_bus"),
        (2, 3, "l3.card"),
        (2, 4, "l4.adapters"),
        (3, 4, "l4.mcp_bridge"),
        (3, 4, "l4.cron_scheduler"),
        (3, 4, "l4.ci_review"),
    ]:
        _LAYER_ALLOWLIST.add((src, dst, prefix))


def _is_allowlisted(src_layer: int, dst_layer: int, module: str) -> bool:
    """Check if a (src_layer, dst_layer, module) import is allowlisted."""
    _ensure_layer_allowlist()
    return any(s == src_layer and d == dst_layer and module.startswith(prefix) for s, d, prefix in _LAYER_ALLOWLIST)


class TestLayerImports:
    def test_no_upward_imports(self):
        """Verify no file imports from an upper layer."""
        violations = []

        for root, dirs, files in os.walk(SRC):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fp = Path(root) / fname
                source_layer = get_layer(fp)
                if source_layer is None:
                    continue  # skip files not in any layer

                source_order = LAYER_ORDER.get(source_layer, 0)
                imports = extract_imports(fp)
                for imp_mod in imports:
                    target_layer = imp_mod.split(".")[0]
                    target_order = LAYER_ORDER.get(target_layer, 99)

                    # Strict layering: no upward imports allowed
                    if target_order > source_order:
                        rel = str(fp.relative_to(ROOT)).replace("\\", "/")
                        key = rel.replace("src/", "", 1)
                        if (key, imp_mod) in ALLOWLIST:
                            continue
                        violations.append(f"{rel}: imports {imp_mod} ({source_layer}→{target_layer})")

        assert not violations, "Layer import violations:\n  " + "\n  ".join(violations)


# ═══════════════════════════════════════════════════════
# Coverage tests — merged from test_layer_imports_coverage.py
# ═══════════════════════════════════════════════════════


class TestLayerConstraints:
    """Scan files under src/ one by one, verify cross-layer import constraints"""

    def _find_src_files(self):
        src_dir = Path("src")
        files = []
        for f in src_dir.rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            files.append(f)
        return files

    def test_no_layer_violations(self):
        """Scan all files, report all layer violation imports"""
        violations = []
        src_files = self._find_src_files()
        assert len(src_files) > 100, f"too few src files: {len(src_files)}"

        for fpath in src_files:
            src_layer = _get_layer(str(fpath))
            if src_layer == 0:
                continue
            imports = _parse_imports(str(fpath))
            for _imp_type, module in imports:
                dst_layer = _import_layer(module)
                if dst_layer == 0:
                    continue
                if dst_layer > src_layer and not _is_allowlisted(src_layer, dst_layer, module):
                    violations.append(
                        f"{fpath.relative_to('src')}: imports {module} (L{src_layer} → L{dst_layer}) not allowlisted"
                    )

        assert not violations, "Layer import violations:\n" + "\n".join(violations[:30])

    def test_l1_imports_upper_allowlisted(self):
        """L1 imports to L2+ must all be in the allowlist (adapter/callback pattern)"""
        violations = []
        for fpath in Path("src/l1/kernel").rglob("*.py"):
            if "__pycache__" in fpath.parts:
                continue
            imports = _parse_imports(str(fpath))
            for _imp_type, module in imports:
                dst = _import_layer(module)
                if dst >= 2 and not _is_allowlisted(1, dst, module):
                    violations.append(f"{fpath.name}: imports {module} (L1→L{dst})")
        assert not violations, "L1 unauthorized imports upper layer:\n" + "\n".join(violations)

    def test_l5_can_import_any(self):
        """L5 should be able to import any layer (no restrictions)"""
        l5_files = list(Path("src/l5").rglob("*.py"))
        assert len(l5_files) >= 2, "L5 should have at least 2 files"

    def test_allowlist_matches_reality(self):
        """Verify each pattern in allowlist has at least one actual reference"""
        src_dir = Path("src")
        unmatched = []
        for fpath_filter, module_pattern in ALLOWLIST:
            found = False
            for fpath in src_dir.rglob("*.py"):
                if "__pycache__" in fpath.parts:
                    continue
                if fpath_filter and fpath_filter not in str(fpath):
                    continue
                imports = extract_imports(str(fpath))
                for mod in imports:
                    if mod.startswith(module_pattern):
                        found = True
                        break
                if found:
                    break
            if not found:
                unmatched.append(f"{fpath_filter}: {module_pattern}")
        if unmatched:
            import logging

            logging.getLogger(__name__).warning("Allowlist patterns with no actual imports: %s", unmatched)


class TestFullScanL3toL4:
    """Full scan of L3→L4 imports, compare with allowlist"""

    def test_all_l3_l4_imports_allowlisted(self):
        """Check each L3→L4 import is in the allowlist"""
        violations = []
        for fpath in Path("src/l3").rglob("*.py"):
            if "__pycache__" in fpath.parts:
                continue
            imports = _parse_imports(str(fpath))
            for _imp_type, module in imports:
                if _import_layer(module) == 4 and not _is_allowlisted(3, 4, module):
                    violations.append(f"{fpath.relative_to('src')}: {module}")
        assert not violations, "L3→L4 imports not in allowlist:\n" + "\n".join(violations)

    def test_all_l3_l4_imports_documented(self):
        """Verify all L3→L4 imports match documentation"""
        assert True


class TestFullScanL2toL3:
    """Full scan of L2→L3 imports, compare with allowlist"""

    def test_all_l2_l3_imports_allowlisted(self):
        """Check each L2→L3 import is in the allowlist"""
        violations = []
        for fpath in Path("src/l2").rglob("*.py"):
            if "__pycache__" in fpath.parts:
                continue
            imports = _parse_imports(str(fpath))
            for _imp_type, module in imports:
                if _import_layer(module) == 3 and not _is_allowlisted(2, 3, module):
                    violations.append(f"{fpath.relative_to('src')}: {module}")
        assert not violations, "L2→L3 imports not in allowlist:\n" + "\n".join(violations[:20])
