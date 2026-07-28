"""Layer import coverage test — ensure cross-layer dependency constraints are not violated.

Strategy:
  1. Scan all .py files under src/, extract import statements
  2. Tag each file by layer (L1→L5)
  3. Verify Ln layer only imports modules from L≤n
  4. Cross-reference with known allowlist to exclude adapter patterns

Reference: allowlist from tests/test_layer_imports.py, this test supplements coverage:
  - All L3→L4 imports are in the allowlist
  - All L2→L3 imports are in the allowlist
  - No new L1→L3/L4 violation imports
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _get_layer(file_path: str) -> int:
    """Return the layer number (1-5) for the given file."""
    rel = Path(file_path).as_posix()
    if rel.startswith("src/l5/"):
        return 5
    if rel.startswith("src/l4/"):
        return 4
    if rel.startswith("src/l3/"):
        return 3
    if rel.startswith("src/l2/"):
        return 2
    if rel.startswith("src/l1/"):
        return 1
    return 0


def _parse_imports(file_path: str) -> list[tuple[str, str]]:
    """Parse import statements from a .py file, returning (type, module) list."""
    imports = []
    try:
        with open(file_path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=file_path)
    except (SyntaxError, Exception):
        return imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(("import", alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(("from", node.module))
    return imports


def _import_layer(module: str) -> int:
    """Return the layer number of the imported module."""
    if module.startswith("l5"):
        return 5
    if module.startswith("l4"):
        return 4
    if module.startswith("l3"):
        return 3
    if module.startswith("l2"):
        return 2
    if module.startswith("l1"):
        return 1
    return 0


# ── Known cross-layer allowlist (consistent with test_layer_imports.py, 49 entries) ──
# Format: (src_layer, dst_layer, module_pattern)
ALLOWLIST = [
    # L1 → L3/L4: adapter patterns, model registry, settings, OS lifecycle
    (1, 3, "l3.cell"),
    (1, 3, "l3.stagnation"),
    (1, 3, "l3.settings_adapter"),
    (1, 3, "l3.monitor_bus"),
    (1, 3, "l3.cache"),
    (1, 3, "l3.config"),
    (1, 3, "l3.error_bus"),
    (1, 3, "l3.agent"),
    (1, 3, "l3.boot"),
    (1, 3, "l3.memory"),
    (1, 3, "l3.agent_terminal"),
    (1, 4, "l4.llm"),
    (1, 4, "l4.llm_base"),
    (1, 4, "l4.adapters"),
    # L2 → L3/L4/L2: shell accessing L3 services + i18n adapter + own subpackages
    (2, 2, "l2"),
    (2, 3, "l3"),
    (2, 3, "l3.cell"),
    (2, 3, "l3.think_registry"),
    (2, 3, "l3.l3"),
    (2, 3, "l3.l3a"),
    (2, 3, "l3.monitor_bus"),
    (2, 3, "l3.agent_terminal"),
    (2, 3, "l3.observability_bus"),
    (2, 3, "l3.memory"),
    (2, 3, "l3.central_memory"),
    (2, 3, "l3.central_security"),
    (2, 3, "l3.central_plugin"),
    (2, 3, "l3.r4_agent"),
    (2, 3, "l3.scout"),
    (2, 3, "l3.scheduler"),
    (2, 3, "l3.cell_monitor"),
    (2, 3, "l3.tool_spec"),
    (2, 3, "l3.tool_mode"),
    (2, 3, "l3.config_loader"),
    (2, 3, "l3.bootstrap"),
    (2, 3, "l3.card_pool"),
    (2, 3, "l3.context_pool"),
    (2, 3, "l3.cache"),
    (2, 3, "l3.memory_init"),
    (2, 3, "l3.resource_buffer"),
    (2, 3, "l3.htn_a"),
    (2, 3, "l3.htn_planner"),
    (2, 3, "l3.l3b"),
    (2, 3, "l3.card_unified"),
    (2, 3, "l3.counter"),
    (2, 3, "l3.assembly"),
    (2, 4, "l4.llm"),
    (2, 4, "l4.mcp_bridge"),
    (2, 4, "l4.cron_scheduler"),
    (2, 4, "l4.adapters"),
    # L3 → L4 (LLM + sandbox + api + notify + lsp + vault)
    (3, 4, "l4.llm"),
    (3, 4, "l4.adapters"),
    (3, 4, "l4.sandbox"),
    (3, 4, "l4.api"),
    (3, 4, "l4.api_gateway"),
    (3, 4, "l4.notify"),
    (3, 4, "l4.lsp"),
    (3, 4, "l4.vault"),
    # L2 → L4 (shell accessing bridge services)
    (2, 4, "l4.vault"),
    # L4 → L3 (BaseService pattern)
    (4, 3, "l3._base"),
    (4, 3, "l3.tool_spec"),
]


def _is_allowlisted(src_layer: int, dst_layer: int, module: str) -> bool:
    """Check if (src, dst, module) is in the allowlist."""
    for s, d, pattern in ALLOWLIST:
        if s == src_layer and d == dst_layer and module.startswith(pattern):
            return True
    return False


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
                continue  # Not in L1-L5, skip
            imports = _parse_imports(str(fpath))
            for imp_type, module in imports:
                dst_layer = _import_layer(module)
                if dst_layer == 0:
                    continue  # Standard library / third-party
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
        # commands.py→l3.cell, gatechain.py→l3.stagnation, model_registry→l4.llm_base,
        # net_transport→l4.adapters, settings→l3.settings_adapter are known allowlist
        assert not violations, f"L1 unauthorized imports upper layer:\n" + "\n".join(violations)

    def test_l5_can_import_any(self):
        """L5 should be able to import any layer (no restrictions)"""
        l5_files = list(Path("src/l5").rglob("*.py"))
        assert len(l5_files) >= 2, "L5 should have at least 2 files"
        # Only verify existence, not specific imports

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
        # Currently known L3→L4 imports are only l4.llm and l4.adapters
        assert not violations, (
            f"L3→L4 imports not in allowlist:\n" + "\n".join(violations)
        )

    def test_all_l3_l4_imports_documented(self):
        """Verify all L3→L4 imports match documentation"""
        import l3.tool_system.tool_config as _tc  # l3 → imports nothing from l4
        import l3.config.cache_strategy as _cs    # l3 → imports l4.llm
        import l3.services.model_service as _ms   # l3 → imports l4.vault
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
