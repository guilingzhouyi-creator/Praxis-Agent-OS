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
    ("l1/kernel/net_transport.py", "l4.adapters.worker_thread"),
    ("l1/kernel/net_transport.py", "l4.adapters.channel_ring"),
    ("l1/kernel/gatechain.py", "l3.stagnation"),
    ("l1/kernel/commands.py", "l3.cell"),
    # L2→L3 shell accessing L3 services
    ("l2/i18n.py", "l4.adapters.i18n_yaml"),
    ("l2/l2_shell/commands.py", "l3.cache"),
    ("l2/l2_shell/completer.py", "l3.agent_terminal"),
    # L3→L4 wiring/adapters (dependency injection)
    ("l3/wiring.py", "l4.adapters.i18n_yaml"),
    ("l3/wiring.py", "l4.adapters.worker_thread"),
    ("l3/wiring.py", "l4.adapters.channel_ring"),
    ("l3/wiring.py", "l4.adapters.bus_memory"),
    ("l3/wiring.py", "l4.adapters.card_registry"),
    ("l3/wiring.py", "l4.adapters.monitor_bus"),
    # L3→L4 cross-layer service calls
    ("l3/config_handlers.py", "l4.api_gateway"),
    ("l3/prompt_engine.py", "l4.lsp"),
    ("l3/tool_pipeline.py", "l4.sandbox.manager"),
    ("l3/tools/_comm.py", "l4.notify"),
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
