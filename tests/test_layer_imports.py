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
    ("l1/kernel/net_transport.py", "l4.adapters.worker_thread"),
    ("l1/kernel/net_transport.py", "l4.adapters.channel_ring"),
    ("l1/kernel/gatechain.py", "l3.stagnation"),
    ("l1/kernel/gatechain.py", "l3.agent.stagnation"),
    ("l1/kernel/commands.py", "l3.cell"),
    ("l1/kernel/model_registry.py", "l4.llm.llm_base"),
    ("l1/kernel/model_registry.py", "l4.llm_base"),
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
    ("l2/l2_shell/commands_agent.py", "l3.cell"),
    ("l2/l2_shell/commands_agent.py", "l3.cell_monitor"),
    ("l2/l2_shell/commands_agent.py", "l3.boot"),
    ("l2/l2_shell/commands_control.py", "l3.l3"),
    ("l2/l2_shell/commands_control.py", "l3.scheduler"),
    ("l2/l2_shell/commands_control.py", "l3.observability_bus"),
    ("l2/l2_shell/commands_control.py", "l3.r4_agent"),
    ("l2/l2_shell/commands_control.py", "l3.cell_monitor"),
    ("l2/l2_shell/commands_control.py", "l3.central_security"),
    ("l2/l2_shell/commands_control.py", "l3.central_memory"),
    ("l2/l2_shell/commands_control.py", "l3.central_plugin"),
    ("l2/l2_shell/commands_control.py", "l3.memory"),
    ("l2/l2_shell/commands_control.py", "l3.resource_buffer.manager"),
    ("l2/l2_shell/commands_control.py", "l3.card_pool"),
    ("l2/l2_shell/commands_control.py", "l3.think_registry"),
    ("l2/l2_shell/commands_control.py", "l3.htn_a"),
    ("l2/l2_shell/commands_control.py", "l3.htn_planner"),
    ("l2/l2_shell/commands_control.py", "l3.cell"),
    ("l2/l2_shell/commands_control.py", "l4.mcp_bridge"),
    ("l2/l2_shell/commands_control.py", "l4.cron_scheduler"),
    ("l2/l2_shell/commands_session.py", "l3.cell"),
    ("l2/l2_shell/commands_session.py", "l3.central_security"),
    ("l2/l2_shell/commands_session.py", "l3.tool_mode"),
    ("l2/l2_shell/commands_system.py", "l3.cache"),
    ("l2/l2_shell/commands_system.py", "l3.cell"),
    ("l2/l2_shell/commands_system.py", "l3.context_pool"),
    ("l2/l2_shell/commands_system.py", "l3.tool_spec"),
    ("l2/l2_shell/commands_system.py", "l3.config_loader"),
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
    ("l2/l2_shell/commands_agent.py", "l3.cell.components.cell_monitor"),
    ("l2/l2_shell/commands_agent.py", "l3.boot.boot"),
    ("l2/l2_shell/commands_control.py", "l3.cell.peers.l3"),
    ("l2/l2_shell/commands_control.py", "l3.scheduler.scheduler"),
    ("l2/l2_shell/commands_control.py", "l3.bus.observability_bus"),
    ("l2/l2_shell/commands_control.py", "l3.memory.r4_agent"),
    ("l2/l2_shell/commands_control.py", "l3.cell.components.cell_monitor"),
    ("l2/l2_shell/commands_control.py", "l3.services.central_security"),
    ("l2/l2_shell/commands_control.py", "l3.memory.memory"),
    ("l2/l2_shell/commands_control.py", "l3.memory.central_memory"),
    ("l2/l2_shell/commands_control.py", "l3.services.central_plugin"),
    ("l2/l2_shell/commands_control.py", "l3.scheduler.think_registry"),
    ("l2/l2_shell/commands_control.py", "l3.bus.htn_a"),
    ("l2/l2_shell/commands_control.py", "l3.bus.htn_planner"),
    ("l2/l2_shell/commands_control.py", "l3.memory.central_memory"),
    ("l2/l2_shell/commands_session.py", "l3.services.central_security"),
    ("l2/l2_shell/commands_session.py", "l3.tool_system.tool_mode"),
    ("l2/l2_shell/commands.py", "l3.services.model_service"),
    ("l2/l2_shell/commands.py", "l3.config.settings_center"),
    ("l2/l2_shell/commands.py", "l3.tool_system.tool_spec"),
    ("l2/l2_shell/commands.py", "l4.vault.credential_vault"),
    ("l2/l2_shell/commands_system.py", "l3.memory.cache"),
    ("l2/l2_shell/commands_system.py", "l3.memory.context_pool"),
    ("l2/l2_shell/commands_system.py", "l3.config.config_loader"),
    ("l2/l2_shell/commands_system.py", "l3.tool_system.tool_spec"),
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
    ("l3/config_handlers.py", "l4.api_gateway"),
    ("l3/prompt_engine.py", "l4.lsp"),
    ("l3/tool_pipeline.py", "l4.sandbox.manager"),
    ("l3/tools/_comm.py", "l4.notify"),
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
