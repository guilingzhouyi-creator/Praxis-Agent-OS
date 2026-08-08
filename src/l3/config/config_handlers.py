"""Config section handlers — domain aggregator.

Each ``cfg_*`` handler processes one section of praxis.yaml and applies its
values to the corresponding kernel/service configuration. The implementations
live in domain submodules below; this module re-exports them so existing
import paths (``config_loader.py``, tests) keep working unchanged.

Domain split:
  config_handlers_kernel.py — kernel / cell / gatechain / constitution / network /
                              persistence / services / cache / devices / language
  config_handlers_llm.py    — llm / tool_rates / tool / htn / prompts / model_spec
  config_handlers_card.py   — card_pool / card_gate / card_types / memory / content_trust
  config_handlers_agent.py  — territories / clearance / agent_role_map / agent_priority /
                              agents / think / loop_control / harness / l3a / skill
  config_handlers_bridge.py — api / api_routes / mcp / credentials / commands / diff
                              (L4-facing; cross-layer imports allowlisted)
"""

from __future__ import annotations

from typing import Any  # noqa: F401 — re-export for annotations

from .config_handlers_agent import (  # noqa: F401
    cfg_agent_priority,
    cfg_agent_role_map,
    cfg_agents,
    cfg_clearance,
    cfg_harness,
    cfg_l3a,
    cfg_loop_control,
    cfg_skill,
    cfg_territories,
    cfg_think,
)
from .config_handlers_bridge import (  # noqa: F401
    cfg_api,
    cfg_api_routes,
    cfg_commands,
    cfg_credentials,
    cfg_diff,
    cfg_mcp,
)
from .config_handlers_card import (  # noqa: F401
    cfg_card_gate,
    cfg_card_pool,
    cfg_card_types,
    cfg_content_trust,
    cfg_memory,
)
from .config_handlers_kernel import (  # noqa: F401
    cfg_cache,
    cfg_cell,
    cfg_constitution,
    cfg_devices,
    cfg_gatechain,
    cfg_kernel,
    cfg_language,
    cfg_network,
    cfg_persistence,
    cfg_services,
)
from .config_handlers_llm import (  # noqa: F401
    _store_tree,
    cfg_htn,
    cfg_llm,
    cfg_model_spec,
    cfg_prompts,
    cfg_tool,
    cfg_tool_rates,
)

__all__ = [
    "_store_tree",
    "cfg_agent_priority",
    "cfg_agent_role_map",
    "cfg_agents",
    "cfg_api",
    "cfg_api_routes",
    "cfg_cache",
    "cfg_card_gate",
    "cfg_card_pool",
    "cfg_card_types",
    "cfg_cell",
    "cfg_clearance",
    "cfg_commands",
    "cfg_constitution",
    "cfg_content_trust",
    "cfg_credentials",
    "cfg_devices",
    "cfg_diff",
    "cfg_gatechain",
    "cfg_harness",
    "cfg_htn",
    "cfg_kernel",
    "cfg_l3a",
    "cfg_language",
    "cfg_llm",
    "cfg_loop_control",
    "cfg_mcp",
    "cfg_memory",
    "cfg_model_spec",
    "cfg_network",
    "cfg_persistence",
    "cfg_prompts",
    "cfg_services",
    "cfg_skill",
    "cfg_territories",
    "cfg_think",
    "cfg_tool",
    "cfg_tool_rates",
]
