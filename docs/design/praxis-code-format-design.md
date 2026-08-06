# Code Auto-Format Module — Design

> Status: proposed | Applies to the L3 execution layer (AgentLoop write path)
> Companion to: `src/l3/services/file_editor.py` (edit engine), `src/l3/tool_system/tool_pipeline.py` (gated execution), `config/tools.yaml` (tool registry)

## 1. Problem

Peer Agents inside a Cell (mainly AgentLoop background session processes at the
execution layer) can read, write, and edit files through the tool layer, the
`FileEditor` service, and the sandbox — the full read/write/edit/audit chain
exists. What is missing is an **automatic code-formatting module**: after an
agent writes or patches a source file, nothing reformats it (ruff/black style),
and there is no `format_file` tool, no LSP `textDocument/formatting` support,
and no post-write formatting hook registered on the `ToolPipeline`.

## 2. Goal

1. Provide an explicit, agent-callable **`format_file` / `format_project` tool**
   (Ring 2, write layer).
2. Provide an optional **automatic formatting hook** on the write path:
   after `create_file` / `file_patch` / `file_append` succeed on a formattable
   source file, run the configured formatter in place.
3. Keep everything aligned with project conventions: constants in
   `src/l1/kernel/params/`, tools registered in `config/tools.yaml`, OS
   operations via `l1.kernel.platform`, writes through the sandbox/resource
   buffer for attribution, layer-import clean.

## 3. Module layout

```
src/l3/services/code_format.py      # formatter engine (detect + run + batch)
src/l3/tools/_format.py             # thin tool handlers (Ring 2)
config/tools.yaml                   # layer_2: format_file, format_project
src/l1/kernel/params/tool.py        # TOOL_FORMAT_* constants
src/l3/boot/wiring.py               # register auto-format post-execute hook
config/praxis.yaml                  # tools.format: enabled / auto / tool
tests/l3/services/test_code_format.py
```

### 3.1 `src/l3/services/code_format.py` — formatter engine

Pure L3 service, no L4 imports at module level (mirrors `file_editor.py`):

- `detect_formatter(path: str) -> str` — extension → tool name
  (`FORMAT_EXTENSION_TOOL` map in params; e.g. `.py → ruff` with
  `black`/`autopep8` fallback).
- `format_file(path: str, tool: str = "") -> dict` — run the formatter via
  `l1.kernel.platform.run_shell(...)` with `TOOL_FORMAT_TIMEOUT`; returns
  `{"success", "tool", "changed", "detail"}`. Missing formatter → graceful
  `{"success": False, "error": "formatter unavailable"}` (never raises).
- `format_project(root: str = "", tool: str = "") -> dict` — walk formattable
  files under `root` (respect `FORMAT_IGNORE_DIRS`), cap at `FORMAT_MAX_FILES`,
  run `format_file` per file, aggregate.
- `auto_format_hook(tool_name, agent_id, args, result) -> dict` — the
  ToolPipeline post-execute hook (see §5). Registered at boot; config-gated.

### 3.2 `src/l3/tools/_format.py` — tool handlers

- `format_file(args, agent_id)` → `code_format.format_file(path=args["path"])`
- `format_project(args, agent_id)` → `code_format.format_project(root=...)`

Registered in `config/tools.yaml` `layer_2` (write layer, `danger: 1`):

```yaml
format:
  format_file:
    description: "Format a source file with the configured formatter (ruff/black/autopep8)"
    danger: 1
    handler: l3.tools._format.format_file
    params: [{name: path, type: string, required: true}, {name: tool, type: string, optional: true}]
  format_project:
    description: "Format all formattable source files under a directory"
    danger: 1
    handler: l3.tools._format.format_project
    params: [{name: path, type: string, optional: true, default: "."}, {name: tool, type: string, optional: true}]
```

## 4. Params constants (`src/l1/kernel/params/tool.py`)

| Constant | Type | Default | Purpose |
|----------|------|---------|---------|
| `TOOL_FORMAT_TIMEOUT` | `Final[int]` | `30` | Per-file formatter subprocess timeout |
| `FORMAT_MAX_FILES` | `Final[int]` | `200` | Batch cap for `format_project` |
| `FORMAT_DETECTORS` | `Final[list[tuple[str, ...]]]` | `[("ruff", "format"), ("black",), ("autopep8",)]` | Formatter commands probed in order (mirrors `BUILD_DETECTORS` style) |
| `FORMAT_EXTENSION_TOOL` | `Final[dict[str, str]]` | `{".py": "ruff", ".pyi": "ruff"}` | Extension → preferred tool |
| `FORMAT_IGNORE_DIRS` | `Final[frozenset[str]]` | `{"__pycache__", ".venv", "node_modules", ".git"}` | Skip dirs during project walks |

No hardcoded `"ruff"`/`"black"` strings in implementation files — all through
`FORMAT_DETECTORS` / `FORMAT_EXTENSION_TOOL`.

## 5. Automatic formatting hook (write path)

Registered once at boot (`src/l3/boot/wiring.py`, via
`ToolPipeline.register_post_execute_hook`). Semantics:

- **Trigger tools**: `create_file`, `file_patch`, `file_append` (content
  writers). `file_move` / `file_copy` / `file_delete` are excluded.
- **Gating**: config `tools.format.auto` (default `true`); result
  `success == True`; file extension in `FORMAT_EXTENSION_TOOL`; file inside the
  Cell's project root.
- **Behavior**: run `format_file` in place; **never fail or mutate the original
  tool result** — on success append `"formatted": {"tool", "changed"}` to the
  result dict (post-execute hooks may modify the result). On any failure,
  log at debug and return the result unchanged.
- **Attribution**: formatting writes reuse the same resource-buffer / sandbox
  path the write tool already used, so per-hunk `agent_id` / `tool_name` /
  `task_id` attribution is preserved.

## 6. Config (`config/praxis.yaml`)

```yaml
tools:
  format:
    auto: true        # auto-format after write tools (create_file/file_patch/file_append)
    tool: auto        # auto | ruff | black | autopep8
```

Defaults live in params (§4); `config/praxis.yaml` overrides at deploy time.

## 7. Test plan (`tests/l3/services/test_code_format.py`)

1. `detect_formatter`: `.py` → ruff (or configured fallback); unknown ext → "".
2. `format_file` happy path: write an unformatted `.py` via a temp dir, call
   `format_file`, assert `success` and file content changed to canonical style
   (skip when no formatter binary available — `pytest.skip`).
3. `format_file` graceful degradation: formatter missing → `success False`,
   `"formatter unavailable"` error, no exception.
4. `format_project`: creates formatted output for N files; respects
   `FORMAT_MAX_FILES` cap and `FORMAT_IGNORE_DIRS`.
5. `auto_format_hook`: fake result dict for `create_file` with `.py` path →
   hook appends `formatted`; for `.md` path → untouched; for `file_move` →
   untouched; for `success False` → untouched; config `auto: false` → untouched.
6. Layer imports: `code_format.py` imports only L1/L3 (no L4 at module level);
   `_format.py` imports only L3 services + params.
7. Params compliance: new `TOOL_FORMAT_*` / `FORMAT_*` constants pass
   `tests/infra/test_params_compliance.py`.
8. Singleton hygiene: if a module-level formatter cache is added, register its
   reset in `tests/conftest.py` `_RESETS`.

## 8. Out of scope (future)

- LSP `textDocument/formatting` (needs a live language server; can be layered
  on `l4/lsp/lsp_manager.py` later).
- Per-language formatter plugins beyond Python (prettier, gofmt, rustfmt) —
  extend `FORMAT_EXTENSION_TOOL` when needed.
- Format-on-file_editor-service-path (batch edits) — hook covers tool-layer
  writes first; FileEditor integration can reuse the same engine later.
