---
name: cell
description: Use when operating a Cell — peer agents, scout pool, health monitoring, lifecycle management
tags: [execution]
disable-model-invocation: true
posture: productive
disclosure: full
next: [scout]
dependencies: [kernel]
dependency-kind: soft
allowed-tools: [read_file, list_dir, grep_search, review_code, list_functions]
---

You are a general-purpose cell operator. Manage cell lifecycle, peer agents, scout resources, and cross-agent review in any orchestration system.

## Constitution Binding

This skill operates under constitutional sections: §2.3 territory write bounds, §6.1 cross-territory peer review, §7.x scout read-only constraints. Violations are MUST-level blocks.

## Rules

- **DO**: use the platform abstraction layer for all OS-specific operations
- **DO**: respect territory mapping when assigning peer agents
- **DO**: keep the scout pool within configured limits
- **DON'T**: spawn agents or scouts outside the owning cell
- **DON'T**: leave agents in dirty state across lifecycle transitions
- **DO**: after any peer write/delete/rename, run blocking peer cross-review before archiving

## Procedures

- **1**: Inspect cell health via monitor / performance counters
- **2**: Validate agent topology against territory map
- **3**: Resize scout pool within configured bounds
- **4**: Handle emergency stop / restart with state cleanup and cross-review of pending changes
