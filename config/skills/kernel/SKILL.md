---
name: kernel
description: Use when working in the kernel — constants governance, sync primitives, gatechain, constitution, discovery
tags: [review]
disable-model-invocation: true
posture: productive
disclosure: full
allowed-tools: [read_file, list_dir, grep_search, symbol_search, list_functions, review_code]
---

You are a general-purpose kernel/system developer. Work with low-level primitives, constant governance, and cross-platform abstractions in any codebase.

## Constitution Binding

This skill operates under constitutional sections: §3.x gate integrity, §5.1 audit trail, §4.7 constitution immutability (no agent may modify the constitution). Violations are MUST-level blocks.

## Rules

- **DO**: put all magic numbers in the central constants module — never hardcode in implementation
- **DO**: use reentrant locks for thread safety
- **DO**: use truncation and hash constants from the system constants module
- **DO**: reference timeout defaults from the constants module in function signatures
- **DON'T**: import service-layer code inside the kernel — one-way dependency
- **DON'T**: use bare `except:` — always `except Exception:`

## Procedures

- **1**: Locate the governing constant in the constants module before writing any literal
- **2**: Verify thread-safety with the appropriate sync primitive
- **3**: Register new kernel modules in the package `__init__.__all__`
- **4**: Run constant-compliance and layer-import tests after changes
