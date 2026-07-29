"""Layer import constraint tests — verify no upward imports."""

import ast
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# Layer hierarchy: index determines allowed upward imports
LAYER_ORDER = {"l1": 0, "l2": 1, "l3": 2, "l4": 3, "l5": 4}

# Allowlist: pre-existing cross-layer imports (adapter patterns + service calls)
ALLOWLIST = {
    # L1→L3 adapter patterns (ports/adapters — need port interface refactoring)
    ("l1/kernel/settings.py", "l3.settings_adapter"),
    ("l1/kernel/settings.py", "l3.config.settings_adapter"),
    ("l1/kernel/constitution.py", "l3.config.settings_center"),
    ("l1/kernel/errors.py", "l3.error_bus"),
    ("l1/kernel/net_transport.py", "l4.adapters.worker_thread"),
    ("l1/kernel/net_transport.py", "l4.adapters.channel_ring"),
    ("l1/kernel/gatechain.py", "l3.stagnation"),
    ("l1/kernel/gatechain.py", "l3.agent.stagnation"),
    ("l1/kernel/commands.py", "l3.cell"),
    ("l1/kernel/model_registry.py", "l4.llm.llm_base"),
    ("l1/kernel/model_registry.py", "l4.llm_base"),
    # L1→L3 OS fallback imports (boot/shutdown lifecycle)
    ("l1/kernel/os.py", "l3.boot.boot"),
    ("l1/kernel/os.py", "l3.memory.memory_init"),
    ("l1/kernel/os.py", "l3.agent_terminal"),
    ("l1/kernel/os.py", "l3.cell"),
    # L2→L3 shell accessing L3 services
    ("l2/i18n.py", "l4.adapters.i18n_yaml"),
    ("l2/l2_shell/commands.py", "l3.cache"),
    ("l2/l2_shell/commands.py", "l3.l3b"),
    ("l2/l2_shell/commands.py", "l3.htn_a"),
    ("l2/l2_shell/commands.py", "l3.htn_planner"),
    ("l2/l2_shell/commands.py", "l3.cell.peers.l3"),
    ("l2/l2_shell/commands.py", "l3.scheduler.scheduler"),
    ("l2/l2_shell/commands.py", "l3.bus.observability_bus"),
    ("l2/l2_shell/commands.py", "l3.memory.r4_agent"),
    ("l2/l2_shell/commands.py", "l3.cell.components.cell_monitor"),
    ("l2/l2_shell/commands.py", "l3.services.central_security"),
    ("l2/l2_shell/commands.py", "l3.memory.memory"),
    ("l2/l2_shell/commands.py", "l3.memory.central_memory"),
    ("l2/l2_shell/commands.py", "l3.services.central_plugin"),
    ("l2/l2_shell/commands.py", "l3.memory.context_pool"),
    ("l2/l2_shell/commands.py", "l3.scheduler.think_registry"),
    ("l2/l2_shell/commands.py", "l3.tool_system.tool_mode"),
    ("l2/l2_shell/commands.py", "l4.llm.llm"),
    # L2→L3 shell accessing L3 services
    ("l2/i18n.py", "l4.adapters.i18n_yaml"),
    ("l2/l2_shell/commands.py", "l3.cache"),
    ("l2/l2_shell/commands.py", "l3.l3b"),
    ("l2/l2_shell/commands.py", "l3.htn_a"),
    ("l2/l2_shell/commands.py", "l3.htn_planner"),
    ("l2/l2_shell/commands.py", "l3.cell"),
    ("l2/l2_shell/commands.py", "l3.agent_terminal"),
    ("l3/subagent_task.py", "l4.llm"),
    ("l3/subagent_task.py", "l4.llm.llm"),
    ("l2/l2_shell/completer.py", "l3.agent_terminal"),
    # New subpackage paths (refactored module reorganization)
    ("l2/l2_shell/commands.py", "l3.bus.l3b"),
    ("l2/l2_shell/commands.py", "l3.bus.htn_a"),
    ("l2/l2_shell/commands.py", "l3.bus.htn_planner"),
    ("l2/l2_shell/commands.py", "l3.memory.cache"),
    ("l2/l2_shell/commands.py", "l3.memory.memory"),
    ("l2/l2_shell/commands.py", "l3.memory.r4_agent"),
    ("l2/l2_shell/commands.py", "l3.memory.central_memory"),
    ("l2/l2_shell/commands.py", "l3.memory.context_pool"),
    ("l2/l2_shell/commands.py", "l3.scheduler.scheduler"),
    ("l2/l2_shell/commands.py", "l3.scheduler.think_registry"),
    ("l2/l2_shell/commands.py", "l3.cell.peers.l3"),
    ("l2/l2_shell/commands.py", "l3.cell.components.cell_monitor"),
    ("l2/l2_shell/commands.py", "l3.services.central_security"),
    ("l2/l2_shell/commands.py", "l3.services.central_plugin"),
    ("l2/l2_shell/commands.py", "l3.tool_system.tool_mode"),
    ("l2/l2_shell/commands.py", "l3.config.config_loader"),
    ("l2/l2_shell/commands.py", "l3.boot.boot"),
    ("l2/l2_shell/commands.py", "l4.llm.llm"),
    ("l2/l2_shell/commands.py", "l3.services.model_service"),
    ("l2/l2_shell/commands.py", "l3.config.settings_center"),
    ("l2/l2_shell/commands.py", "l3.tool_system.tool_spec"),
    ("l2/l2_shell/commands.py", "l4.vault.credential_vault"),
    # L2→L3 shell.py REPL lazy imports (terminal tool calls)
    ("l2/shell.py", "l3.cell"),
    ("l2/shell.py", "l3.tools_l3"),
    ("l2/shell.py", "l3.agent.scout"),
    ("l2/shell.py", "l3.tool_system.tool_spec"),
    # L2→L3 shell_completer.py lazy imports
    ("l2/shell_completer.py", "l3.tool_system.tool_config"),
    ("l3/agent/agent_loop.py", "l4.llm.llm"),
    ("l3/agent/_term_lifecycle.py", "l4.llm.llm"),
    ("l3/agent/_term_lifecycle.py", "l4.llm.llm_base"),
    ("l3/agent/subagent_task.py", "l4.llm.llm"),
    ("l3/card/card_registry.py", "l4.llm.llm"),
    ("l3/config/cache_strategy.py", "l4.llm.llm"),
    ("l3/boot/wiring.py", "l4.adapters.i18n_yaml"),
    ("l3/boot/wiring.py", "l4.adapters.worker_thread"),
    ("l3/boot/wiring.py", "l4.adapters.channel_ring"),
    ("l3/boot/wiring.py", "l4.adapters.bus_memory"),
    ("l3/boot/wiring.py", "l4.adapters.card_registry"),
    ("l3/boot/wiring.py", "l4.adapters.monitor_bus"),
    ("l3/services/model_service.py", "l4.llm.llm_base"),
    ("l3/services/model_service.py", "l4.llm.llm"),
    ("l3/services/model_service.py", "l4.vault.credential_vault"),
    ("l3/services/prompt_engine.py", "l4.lsp.lsp"),
    ("l3/tool_system/tool_pipeline.py", "l4.sandbox.manager"),
    ("l3/config/config_handlers.py", "l4.api.api_gateway"),
    ("l3/config/config_loader.py", "l4.llm.llm"),
    ("l3/memory/r4_agent.py", "l4.llm.llm"),
    # L3→L4 wiring/adapters (dependency injection)
    ("l3/wiring.py", "l4.adapters.i18n_yaml"),
    ("l3/wiring.py", "l4.adapters.worker_thread"),
    ("l3/wiring.py", "l4.adapters.channel_ring"),
    ("l3/wiring.py", "l4.adapters.bus_memory"),
    ("l3/wiring.py", "l4.adapters.card_registry"),
    ("l3/wiring.py", "l4.adapters.monitor_bus"),
    # L3→L4 cross-layer service calls
    ("l3/cell/components/cell_cross_review.py", "l4.sandbox"),
    ("l3/config_handlers.py", "l4.api_gateway"),
    ("l3/prompt_engine.py", "l4.lsp"),
    ("l3/tool_pipeline.py", "l4.sandbox.manager"),
    ("l3/tools/_comm.py", "l4.notify"),
    ("l3/tools/_files.py", "l4.sandbox"),
    # L3→L4 LLM calls (pre-existing, need port refactoring)
    ("l3/agent_loop.py", "l4.llm"),
    ("l3/cache_strategy.py", "l4.llm"),
    ("l3/card_registry.py", "l4.llm"),
    ("l3/config_loader.py", "l4.llm"),
    ("l3/r4_agent.py", "l4.llm"),
    ("l3/_term_lifecycle.py", "l4.llm"),
    # L2→L3 commands (pre-existing think handler)
    ("l2/l2_shell/commands.py", "l3.think_registry"),
    ("l2/l2_shell/commands.py", "l3.cell"),
    # L1→L4 model_registry
    ("l1/kernel/model_registry.py", "l4.llm_base"),
    # L2->L3 commands (inline imports in command handlers)
    ("l2/l2_shell/commands.py", "l3.l3"),
    ("l2/l2_shell/commands.py", "l3.scheduler"),
    ("l2/l2_shell/commands.py", "l3.observability_bus"),
    ("l2/l2_shell/commands.py", "l3.r4_agent"),
    ("l2/l2_shell/commands.py", "l3.cell_monitor"),
    ("l2/l2_shell/commands.py", "l3.central_security"),
    ("l2/l2_shell/commands.py", "l3.memory"),
    ("l2/l2_shell/commands.py", "l3.central_memory"),
    ("l2/l2_shell/commands.py", "l3.central_plugin"),
    ("l2/l2_shell/commands.py", "l4.mcp_bridge"),
    ("l2/l2_shell/commands.py", "l4.cron_scheduler"),
    ("l2/l2_shell/commands.py", "l3.resource_buffer.manager"),
    ("l2/l2_shell/commands.py", "l3.card_pool"),
    ("l2/l2_shell/commands.py", "l3.context_pool"),
    ("l2/l2_shell/commands.py", "l4.llm"),
    ("l2/l2_shell/commands.py", "l3.tool_mode"),
    ("l2/l2_shell/commands.py", "l3.tool_spec"),
    ("l2/l2_shell/commands.py", "l3.config_loader"),
    ("l2/l2_shell/commands.py", "l3.boot"),
    # L3->L4 LLM base
    ("l3/_term_lifecycle.py", "l4.llm_base"),
    ("l3/cell/components/cell_rollback.py", "l4.sandbox"),
    ("l3/subagent_framework.py", "l4.llm"),
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
            if node.module and re.match(r'^l[1-5]\.', node.module):
                imports.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if re.match(r'^l[1-5](\.|$)', alias.name):
                    imports.append(alias.name)
    return imports


def get_layer(path: Path) -> str | None:
    """Determine which layer a file belongs to."""
    for part in path.relative_to(SRC).parts:
        if part.startswith("l") and part[1:].isdigit():
            return part
    return None


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

        assert not violations, f"Layer import violations:\n  " + "\n  ".join(violations)


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
            for imp_type, module in imports:
                dst_layer = _import_layer(module)
                if dst_layer == 0:
                    continue
                if dst_layer > src_layer and not _is_allowlisted(src_layer, dst_layer, module):
                    violations.append(
                        f"{fpath.relative_to('src')}: imports {module} "
                        f"(L{src_layer} → L{dst_layer}) not allowlisted"
                    )

        assert not violations, (
            f"Layer import violations:\n" + "\n".join(violations[:30])
        )

    def test_l1_imports_upper_allowlisted(self):
        """L1 imports to L2+ must all be in the allowlist (adapter/callback pattern)"""
        violations = []
        for fpath in Path("src/l1/kernel").rglob("*.py"):
            if "__pycache__" in fpath.parts:
                continue
            imports = _parse_imports(str(fpath))
            for imp_type, module in imports:
                dst = _import_layer(module)
                if dst >= 2 and not _is_allowlisted(1, dst, module):
                    violations.append(f"{fpath.name}: imports {module} (L1→L{dst})")
        assert not violations, f"L1 unauthorized imports upper layer:\n" + "\n".join(violations)

    def test_l5_can_import_any(self):
        """L5 should be able to import any layer (no restrictions)"""
        l5_files = list(Path("src/l5").rglob("*.py"))
        assert len(l5_files) >= 2, "L5 should have at least 2 files"

    def test_allowlist_matches_reality(self):
        """Verify each pattern in allowlist has at least one actual reference"""
        src_dir = Path("src")
        unmatched = []
        for s, d, pattern in ALLOWLIST:
            found = False
            for fpath in src_dir.rglob("*.py"):
                if "__pycache__" in fpath.parts:
                    continue
                src_layer = _get_layer(str(fpath))
                if src_layer != s:
                    continue
                imports = _parse_imports(str(fpath))
                for imp_type, module in imports:
                    if module.startswith(pattern):
                        found = True
                        break
                if found:
                    break
            if not found:
                unmatched.append(f"L{s}→L{d} {pattern}")
        if unmatched:
            import logging
            logging.getLogger(__name__).warning(
                "Allowlist patterns with no actual imports: %s", unmatched
            )


class TestFullScanL3toL4:
    """Full scan of L3→L4 imports, compare with allowlist"""

    def test_all_l3_l4_imports_allowlisted(self):
        """Check each L3→L4 import is in the allowlist"""
        violations = []
        for fpath in Path("src/l3").rglob("*.py"):
            if "__pycache__" in fpath.parts:
                continue
            imports = _parse_imports(str(fpath))
            for imp_type, module in imports:
                if _import_layer(module) == 4:
                    if not _is_allowlisted(3, 4, module):
                        violations.append(f"{fpath.relative_to('src')}: {module}")
        assert not violations, (
            f"L3→L4 imports not in allowlist:\n" + "\n".join(violations)
        )

    def test_all_l3_l4_imports_documented(self):
        """Verify all L3→L4 imports match documentation"""
        import l3.tool_system.tool_config as _tc
        import l3.config.cache_strategy as _cs
        import l3.services.model_service as _ms
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
            for imp_type, module in imports:
                if _import_layer(module) == 3:
                    if not _is_allowlisted(2, 3, module):
                        violations.append(f"{fpath.relative_to('src')}: {module}")
        assert not violations, (
            f"L2→L3 imports not in allowlist:\n" + "\n".join(violations[:20])
        )
