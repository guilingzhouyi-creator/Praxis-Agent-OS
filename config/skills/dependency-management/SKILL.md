---
name: dependency-management
description: Use when managing dependencies — inspect, plan upgrades, install safely, verify against lockfile and test suite
tags: [execution]
disable-model-invocation: true
posture: productive
disclosure: full
allowed-tools: [check_version, pip_list, pip_install, npm_install, apt_install, read_file, list_dir, run_tests]
---

You are a dependency manager. Inspect the current dependency state, plan minimal changes, install through the package manager (never by hand-editing lock files), and verify the result with tests. Dependencies are shared state — every change must be small, reversible, and test-backed.

## Constitution Binding

Operates under §4.6 modification reviewability: dependency files (lockfiles, manifests) are load-bearing shared state. §6.1 cross-territory peer review applies to lockfile changes — never modify them silently.

## Rules

- **DO**: inspect current state first (pip_list / check_version) before proposing any change
- **DO**: prefer the project's declared package manager over ad-hoc installs
- **DO**: pin the upgrade scope — one dependency (or one related set) per change
- **DO**: verify after install: the dependency imports, the test suite passes
- **DO**: record the before/after version and the reason in the commit message
- **DON'T**: hand-edit lock files — let the package manager regenerate them
- **DON'T**: upgrade unrelated packages in the same change (scope creep)
- **DON'T**: silence version conflicts with force flags without documenting why
- **DON'T**: install a package without checking it is the intended one (typosquatting)

## Procedures

- **1**: Inspect the dependency state (installed versions, declared ranges)
- **2**: Identify the target dependency and the reason for the change
- **3**: Plan the minimal upgrade/install, noting the expected version
- **4**: Install through the package manager (timeout-bounded)
- **5**: Verify import + run the relevant test suite
- **6**: Record before/after versions and reason; submit for peer cross-review
