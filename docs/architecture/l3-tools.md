# L3 — Tool Layer (20 implementations + tool system)

The tool layer is what agents can do. 20 handlers in `l3/tools/` produce
structured dicts for the 9-step pipeline; `l3/tool_system/` (10 files)
defines how tools are declared, registered, gated, and executed.

## Tool inventory (by domain)

| Domain | Tools | Notes |
|--------|-------|-------|
| **File** | `_files.py` read_file / write_file / list_dir / edit / copy / delete … | via resource_buffer; the biggest family |
| **Search** | `_search.py` grep / glob / file_search | cross-platform (rg/grep + pure-Python fallback) |
| **Git** | `_git.py` git_commit / git_push / git_status … | |
| **Build** | `_build.py` build_project / test_project / deploy / db_migrate / rollback | detector-command lists (no hardcoded toolchain) |
| **Code** | `_code.py` symbol_search / issue detection | regex scanners |
| **Web** | `_web.py` web_fetch / web_search | urllib + truncation |
| **Package** | `_package.py` pip/npm/apt/cargo install/list | PackageManager service |
| **Terminal** | `_terminal.py` execute_shell | RING_3 approval-gated; cross-platform run_shell |
| **Memory** | `_memory.py` memory_store / memory_retrieve | L3 MemoryManager |
| **Archive** | `_archive.py` archive save/load/query | SQLite fonds/series/ref-code |
| **Config** | `_config.py` config_get / config_set | SettingsCenter |
| **Env** | `_env.py` env_get / env_list / reset_workspace | reset = RING_3 factory reset |
| **Comm** | `_comm.py` ask_user / confirm | L3A awaiting flow, headless degrade |
| **Peer** | `_peer.py` agent_list / agent_heartbeat | IPC keepalive |
| **SubAgent** | `_subagent.py` review (read-only) / deploy (write+approval) / scout (async) | mounts a subagent as one tool |
| **LSP** | `_lsp.py` go-to-def / find-refs / hover | wraps L4 LspManager, Ring 1 read-only |
| **Skill** | `_skills.py` list_skills / use_skill | tag/tool filters |
| **Logging** | `_logging.py` log_info / log_error | per-agent tagged |
| **Deps** | `_deps.py` check_version | importlib.metadata |

## Tool system (how tools are declared and gated)

| Module | Role |
|--------|------|
| `tool_spec.py` | ToolSpec — plugin registration, `tools_*.py` auto-discovery, execution middleware, categories, JSON export |
| `tool_registry.py` | ToolRegistry — MapRegistry-based: mute system, plugins, middleware |
| `tool_policy.py` | 3-layer visibility (handler / LLM context / pipeline) — SESSION > AGENT > ROLE > CELL > GLOBAL; `require_approval` |
| `tool_pipeline.py` | **9-step pipeline**: ring check → rate limit → constitution → GateChain G1–G5 → approval → execute → audit → record |
| `tool_params.py` | ParamSpec / ReturnSpec declarations with type validation |
| `tool_mode.py` | global read/write mode (write = all rings, read = Ring 1 only) |
| `tool_config.py` | `tools.yaml`-driven definitions; three-ring integration chain-filter API |

### Pipeline (9 steps)

```
ring gate → rate limit → constitution → gatechain G1-G5 → approval policy
→ sandbox (profile-gated) → execute handler → result record → reference channel
```

**GateChain posture linkage:** when the system posture is full-power attack
(`security.mode=security-test` + detection-bypass confirmed), G4 skips the
L3 review WARN for high-danger tools (`danger >= GATECHAIN_ESCALATION_DANGER`)
but still records the call for the audit trail. The full-power decision and
the G4 bypass are recorded via the injected L1 metric sink
(`security.gate.g4.full_power`) — the kernel never imports L3; boot wires
`set_metric_sink()` (same pattern as the posture provider).

## Config surface

- `config/tools.yaml` — 68 tool definitions by ring layer (danger, params)
- Ring tiers: Ring 1 (read-only), Ring 2.5 (write+approval), Ring 3 (danger)

## Integration

- `l3-card-lifecycle.md`: agents execute card steps through these tools.
- `l4-bridge.md`: MCP bridge + WS `rpc` expose tools to frontends.
