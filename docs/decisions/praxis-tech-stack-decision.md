---
fonds: DECISION
series: Praxis-v1
title: NOMOS Praxis Tech Stack and Architecture Decision
timestamp: 2026-07-21T18:00
L3: NOMOSAgent
status: discussing
relations: [ARCHIVE-decisions-001]
---

# NOMOS Praxis — Tech Stack and Architecture Decision

## Core Decisions

All five issues converged: GUI=Python webview, kernel=pure Python, territory=by layer (A), L3=pure rule engine, MVP=4 days 5 tools.

## Design Rules

1. GUI must use pywebview——the only solution meeting <500ms startup, <50MB package, three platforms, and zero friction with Python.
2. Kernel must remain pure Python——the current bottleneck is LLM API calls (500ms-5s), not computation paths (microsecond level), introducing Rust/C++ would not be worth it.
3. Territory must be divided by layer (Scheme A)——Agent A (routes/params/middleware/auth/i18n), Agent B (pages/services/visa/cache/config), Agent C (tests/security/nomos_mcp/memories/scripts).
4. L3 must use a pure rule engine ~100 lines of Python——Task Card already structures intent, no LLM reasoning needed. Gradual path: initially hardcoded routing table, later auto-generated from the constitution.
5. MVP must be completed in 4 days——must not include multi-agent approval, multi-unit, Ring Ω, or desktop packaging.
6. `config/` must belong to Agent B (business layer)——config's business coupling is in services/, not routes/.
7. If pywebview is not compatible with Python 3.14, must fall back to tkinter + tkhtmlview (do not block P0).

## Specifications

- Startup requirements: pywebview measured 200-300ms, package 15-25MB, three-platform native WebView with zero additional distribution
- Performance bottleneck data: Ring eviction <1μs, gate check <1μs, JSON serialization ~2μs, SHA-256 ~1.5μs, LLM API 500ms-5s (only bottleneck, 300,000x difference)
- `L3RuleEngine.match()`: ~20 lines domain lookup table + intent keyword matching, returns AgentId
- `L3RuleEngine.converge()`: ~15 lines priority merging, on conflict selects higher reputation Agent
- MVP component estimates: Intent Card 0.5 day, L3 0.5 day, 1 Agent+5 Tools 1 day, Dual Ring Panel 1 day, Activity Stream Card 0.5 day, pywebview integration 0.5 day
- MVP 5 tools: read_file(0, read file), grep_search(0, text search), replace_string_in_file(1, modify file), run_in_terminal(1, execute command), read_fingerprint(0, reverse-lookup tool output source)
- P1 candidates: Second Agent + approval flow first (prove "multi-agent > single agent"), then tool ring fingerprint chain visualization, P2 memory backfill hints, P3 desktop packaging
- Integration path (Issue #6): MVP stage `--gui` starts Praxis, no flag starts Flask dev; Praxis imports existing code directly via `import nomos.rings`, not via HTTP
- Territory division (Scheme A): Agent A (routes/params/middleware/auth/i18n, read-oriented), Agent B (pages/services/visa/cache/config, balanced read/write), Agent C (tests/security/nomos_mcp/memories/scripts, read-only audit + write tests, security fixes can span all territories)
- Cross-territory operation estimate: ~15-20% (80% of operations stay within territory, no blocking)

## Exclusions

- Rust Tauri: excluded (package is small, but requires Rust bridge layer, heavy maintenance burden for a single developer maintaining Python+Rust)
- C++ Qt: excluded (startup ~1s > 500ms, package > 50MB, complex bridge and high maintenance cost)
- Electron: excluded (startup ~2s > 500ms, package > 100MB > 50MB constraint)
- Rust/C++ rewrite of fingerprint computation: excluded (1000 calls total 1.5ms, less than 1/200 of a single API call)
- L3 using small/large model: excluded (structured intent doesn't need NLP understanding, introduces additional 200ms-2s API latency)
- MVP estimate 6-8 days: excluded (OpenCode's 4-day estimate is reasonable, Card and Dual Ring Panel share styles, no separation needed)
- Territory Scheme B (by domain) and Scheme C (manual): excluded (Scheme A by layer has the least cross-territory approvals)
- `config/` belonging to Agent A: excluded (config's business coupling is in services/, should belong to Agent B)
