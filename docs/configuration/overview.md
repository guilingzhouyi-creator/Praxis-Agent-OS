# Configuration System

Praxis uses a **declarative, layered configuration architecture** with auto-discovery.

## File Layout

```
config/
  praxis.yaml              — Main project config (kernel, cell, LLM, gatechain, API, diff, etc.)
  commands.yaml            — L2 Shell command definitions and SubAgent specs
  tools.yaml               — Tool definitions by ring layer (RING_1 / RING_2_5 / RING_3)
  .praxis-rules.md         — Constitution rules (parsed by constitution.py)
  .mcp.json                — MCP server definitions
  discovery/               — Auto-discovered structural config (overlays params defaults)
    agent_configs.yaml     — Agent roles, clearance, priorities, event types, injection patterns
    build_detectors.yaml   — Build/test framework auto-detection commands
    danger_levels.yaml     — Tool danger levels, gate mappings, ring maps
    error_codes.yaml       — Error code definitions and i18n translations
    providers.yaml         — LLM provider URLs, model names, env vars, IPC sockets
```

## Configuration Layers (lowest to highest priority)

```
 1. params/*.py            — Compile-time defaults (timeouts, limits, thresholds)
    ↓ fallback
 2. config/discovery/*.yaml — Structural configuration (auto-discovered at boot)
    ↓ merge
 3. config/praxis.yaml     — Project-level deployment config (applied by config_handlers)
    ↓ override
 4. .praxis_settings.json  — Runtime overrides (set via API or L2 Shell)
```

### Layer 1: params/*.py

Atomic constants (timeouts, limits, thresholds) defined in five sub-modules:

| File | Purpose | Example |
|------|---------|---------|
| `kernel.py` | Allocator, sync, process, gatechain, VFS | `ALLOCATOR_DEFAULTS.tokens=4096` |
| `agent.py` | Agent roles, terminal, loop, card, scout | `AGENT_LOOP_DEFAULT_TIMEOUT=120.0` |
| `tool.py` | Tool danger, timeouts, rate limits, HTN | `TOOL_BUILD_TIMEOUT=300` |
| `api.py` | API gateway, LLM, network, IPC, env vars | `API_GATEWAY_PORT=8080` |
| `system.py` | Cache, memory rings, data paths, truncation | `LOG_TRUNC_200=200` |

### Layer 2: config/discovery/*.yaml (ConfigDiscovery)

Structural configuration discovered at boot by `l1.kernel.discovery`.

**Section name** mappings from `_init_discovery()` boot step:

| YAML file | Section names | Defaults source |
|-----------|---------------|-----------------|
| `agent_configs.yaml` | `central_roles`, `agent_clearance`, `agent_priority`, `agent_role_map`, `priority_gradient`, `reputation_defaults`, `agent_defaults`, `agent_id_prefixes`, `event_types`, `card_builder_modes`, `injection_patterns`, `constitution`, `resource_keys`, `htn_default_tools`, `builtin_rule_defs`, `memory_persist_files`, `search.exclude_dirs`, `search.exclude_exts`, `resource_buffer.*`, `skill_dirs`, `shell_aliases` | `params/agent.py` |
| `build_detectors.yaml` | `build_detectors`, `test_detectors` | `params/tool.py` |
| `danger_levels.yaml` | `danger_levels`, `danger_to_gates`, `ring_gates`, `ring_num_map`, `ring_name_map`, `gatechain_danger_levels`, `gatechain_pattern_template` | `params/tool.py`, `params/kernel.py` |
| `error_codes.yaml` | `error_codes`, `i18n.zh-CN` | `l1/kernel/errors.py` |
| `providers.yaml` | `provider_urls`, `default_models`, `provider_discovery`, `anthropic_api_version`, `llm.empty_response_waits`, `reasoning_effort_levels`, `mcp_default_url`, `search_default_url`, `ipc_sockets`, `env_vars` | `params/api.py` |

**Adding new values**: Simply add new keys to the appropriate YAML file. No code changes needed.

```yaml
# Example: adding a Go build detector to build_detectors.yaml
build_detectors:
  go: {cmd: [go, build]}
```

### Layer 3: config/praxis.yaml

Main deployment configuration. Handlers registered in `config_loader.py`:

| Section | Handler | Loads into |
|---------|---------|------------|
| `kernel` | `cfg_kernel` | SettingsCenter |
| `cell` | `cfg_cell` | SettingsCenter |
| `llm` | `cfg_llm` | SettingsCenter |
| `diff` | `cfg_diff` | SettingsCenter + immediate color scheme |
| `constitution` | `cfg_constitution` | In-memory action sets |
| `gatechain` | `cfg_gatechain` | SettingsCenter |
| `card_gate` | `cfg_card_gate` | CardGate instance |
| ... | ... | ... |

### Layer 4: .praxis_settings.json

Runtime overrides persisted automatically. Modified via:

```
POST /api/settings     # set a key
L2 Shell /settings     # view/modify settings
```

## Per-executor Model Specs (`model_spec`)

`config/praxis.yaml` section `model_spec:` configures model / context /
reasoning strength per executor. Resolution cascade in
`ModelService.resolve_dict(spec_name)` (higher wins):

```
1. overrides (per-call, e.g. spec.model_config)
2. model_spec.{name}            (exact spec, e.g. model_spec.scout.temperature)
3. model_spec.{prefix}.defaults (platform defaults, e.g. model_spec.scout.defaults.*)
4. llm.*                         (global llm section)
```

Supported executor spec names and their consumers:

| spec_name | Consumer | Default |
|-----------|----------|---------|
| `scout` | Scout pool (`scout.py`) | 2048 tokens / 0.3 temp |
| `l3a` | L3A session main model | 4096 tokens / 0.7 temp |
| `l3a_subagent` | L3A subagent pool (`l3a/subagent.py`) | 2048 / 0.3 |
| `subagent` | Cell SubAgent (`subagent_task.py`, spec.model_spec) | 2048 / 0.3 |
| `r4_agent` | R4 archive agent (`r4_agent.model_spec`) | 2048 / 0.3 |

Keys per spec: `max_tokens`, `temperature`, `reasoning_effort`
(`none|low|medium|high`), `thinking_budget` (token budget, 0 = provider
default). `model` is omitted by default and inherits `llm.model`; set it
per executor to diverge.

Runtime override (persisted to `.praxis_settings.json`):

```
PUT /api/v2/model-spec/{name}   {"temperature": 0.5, "reasoning_effort": "medium"}
GET /api/v2/model-spec          # list resolved specs
```

### Named strategy packs (runtime switching)

`model_spec.strategies` in praxis.yaml defines named packs that switch an
executor's model/context/reasoning profile at runtime:

```yaml
model_spec:
  strategies:
    fast:     {max_tokens: 2048, temperature: 0.3, reasoning_effort: none,   thinking_budget: 0}
    balanced: {max_tokens: 4096, temperature: 0.5, reasoning_effort: low,    thinking_budget: 2048}
    deep:     {max_tokens: 8192, temperature: 0.7, reasoning_effort: high,   thinking_budget: 8192}
```

API:

```
PUT    /api/v2/model-spec/{name}/strategy  {"strategy": "deep"}     # apply pack (immediate)
GET    /api/v2/model-spec/{name}/strategy                           # current strategy + overrides
DELETE /api/v2/model-spec/{name}/strategy                           # restore defaults
PUT    /api/v2/model-spec/strategy/apply  {"strategy": "deep", "specs": ["l3a", "scout"]}  # batch; specs: ["all"]
```

Applied packs write the exact layer (`model_spec.{name}.{key}`, L3,
persisted), which outranks the executor defaults in the resolve cascade.

## Reading Configuration in Code

```python
from l1.kernel.discovery import get_config

# Read from discovery (falls back to params defaults)
detectors = get_config("build_detectors") or {}

# For atomic params constants, import directly from params
from l1.kernel.params.tool import TOOL_BUILD_TIMEOUT
```

## ConfigDiscovery Architecture

```python
src/l1/kernel/discovery.py
  register(name, defaults)       # Register a config section with Python-side defaults
  register_discovery_dir(path)   # Add a directory to scan for YAML snippets
  discover()                     # Scan YAML files and merge into registry
  get_config(name, default)      # Read merged config
  get_source(name, default)      # Read originally registered defaults only
  set_config(name, key, value)   # Runtime override
  reset()                        # Reset to defaults (for testing)
```

Boot sequence: `load_constitution → init_discovery → load_config → ...`
