# NOMOS Praxis — Agent OS (v0.3.0 "Aether")

Python 3.11+ Agent OS for orchestrating LLM-based agents. Five-layer architecture from bare-metal kernel to user CLI.

## Quick start

```bash
pip install -e ".[test]"          # install + dev deps
python src/main.py boot           # boot kernel + cell
python src/main.py health         # kernel self-test
python src/main.py status         # full system status
python src/main.py ps             # list processes
python src/main.py card "<intent>"  # dispatch a card
python -m l2.l2_shell             # interactive L2 Shell
```

## Test commands

```bash
python -m pytest tests/ -x -q                                               # all tests
python tests/runner.py                                                      # batch 1 (fast) + batch 2 (slow)
python -m pytest tests/test_kernel.py -x -q                                 # single file
python tests/runner.py test_kernel                                           # single via runner
python -m pytest tests/ -k "kernel" -x -q                                   # keyword filter
python -m pytest tests/test_layer_imports.py -x -q                          # layer import constraint
```

## Architecture

```
src/l5/ — User layer: cli.py (296 lines), agent_runtime.py
src/l4/ — Bridge: API gateway, LLM engine+providers, sandbox, MCP, search, LSP, vault
src/l3/ — Cell layer (~19K lines): agents, memory, cards, scheduler, tool pipeline, discussion
src/l2/ — Shell: 40 commands, i18n, agent selector
src/l1/kernel/ — Kernel primitives: sync, event, constitution, allocator, gatechain, VFS, IPC
src/l1/kernel/params/ — 694 constants across 5 sub-modules (kernel/agent/tool/api/system)
```

### Import rules (enforced by `tests/test_layer_imports.py`)
- L5 → L4/L3/L2/L1; L4 → L3/L2/L1; L3 → L2/L1; L2 → L1 only; L1 cannot import upper layers
- 53 pre-existing cross-layer imports are allowlisted in that test

## Key conventions

- **All magic numbers go in `src/l1/kernel/params/`** — never hardcode in implementation files
- **New kernel modules** must be exported in `kernel/__init__.py` `__all__`
- **New config items** register defaults in `kernel/settings.py` `DEFAULTS`
- **Use `threading.RLock`** (reentrant) for thread locks
- **Never import `services/` inside `kernel/`** — one-way dependency
- **Register tools** via `ToolSpec` with ring/danger/parameters in `config/tools.yaml`
- **No bare `except:`** — use `except Exception:`
- **Double quotes** for strings (ruff `quote-style = "double"`), line-length 120

## L3 + L4 conventions (enforced during code review)

- **Use `l1.kernel.platform` abstractions** for all OS-specific operations: `grep_cmd()`, `run_shell()`, `IS_WINDOWS`, `IS_POSIX`. Never self-implement platform-specific subprocess calls (e.g., `rg` → `grep` fallback with `shell=True`).
- **Truncation literals**: use `LOG_TRUNC_*` constants from `params/system.py` (`LOG_TRUNC_40` through `LOG_TRUNC_10000`). Never write `[:40]`, `[:3000]` etc. directly.
- **Hash truncation**: use `HASH_TRUNC_SHORT` (8), `HASH_TRUNC_MEDIUM` (12), `HASH_TRUNC_LONG` (16).
- **Memory importance weights**: use `MEMORY_IMPORTANCE_*` and `MEMORY_PRESSURE_*` constants from `params/system.py`.
- **Timeout defaults in function signatures**: reference `params/tool.py` or `params/system.py` constants, not raw numbers.
- **File path strings**: centralize in `params/system.py` or `paths.py`. Avoid `"*.json"`, `"foo/bar.yaml"` in implementation code.
- **Package manager timeouts**: use `TOOL_PACKAGE_MANAGER_TIMEOUT`, `TOOL_PIP_INSTALL_TIMEOUT`, etc. from `params/tool.py`.

## Testing quirks

- **Singleton pollution**: Many services use global `_xxx = None` singletons. `tests/conftest.py` has an `autouse` fixture that resets ~20 known singletons before every test. When writing tests for new services, add their reset function to `_RESETS` in conftest.
- **Layer import test** (`test_layer_imports.py`) checks all `.py` files. New cross-layer imports must be allowlisted there.
- **Runner batches**: `tests/runner.py` splits into Batch 1 (fast core, ~5s) and Batch 2 (slow extended, ~75s: r4_agent, archive, convention).

## LLM config

Default: `ollama` / `qwen2.5-coder:7b` at `localhost:11434`. Configure via `config/praxis.yaml` or env vars (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_URL`, etc.).

## Project structure

| Path | Description |
|------|-------------|
| `config/praxis.yaml` | Main config (kernel, cell, LLM, constitution, gatechain, API) |
| `config/commands.yaml` | 40 L2 shell command definitions |
| `config/tools.yaml` | 70+ tool definitions by ring layer |
| `config/.nomos-rules.md` | Constitution rules (parsed by `constitution.py`) |
| `config/.mcp.json` | MCP server definitions |
| `locales/` | i18n: en, zh-CN, ja, ko |
| `memories/` | Runtime agent memory persistence |
| `.opencode/skills/` | 7 Praxis-specific OpenCode skills (architecture, card, cell, kernel, scout, self, tool-pipeline) |

## Key files

- `src/main.py` — CLI entry: `python main.py <boot|health|ps|card|tools|audit|chain|interrupts|devices|status>`
- `src/l5/cli.py` — CLI command implementations
- `src/l1/kernel/os.py` — OS lifecycle (boot/shutdown/restart/watchdog)
- `src/l1/kernel/constitution.py` — Constitutional rules engine (highest authority)
- `src/l3/tool_system/tool_pipeline.py` — 9-step tool execution pipeline
- `src/l3/card/card_registry.py` — Card lifecycle management
- `src/l3/boot/boot.py` — 7-step system bootstrap
- `src/l3/boot/lifecycle.py` — Factory reset, singleton reset, disk wipe
