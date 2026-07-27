---
fonds: DECISION
series: Praxis-v1
title: NOMOS Praxis MVP Decision
timestamp: 2026-07-21T18:30
L3: NOMOSAgent
participants: AtomCode, OpenCode, NOMOSAgent
status: converged
relations: [ARCHIVE-decisions-002, ARCHIVE-design-001]
---

# NOMOS Praxis — MVP Decision

## Core Decisions

Five resolutions converged: GUI=pywebview, kernel=pure Python, territory=by layer (A/B/C), L3=pure rule engine, MVP=4 days 5 tools.

## Design Rules

1. GUI must use Python webview (pywebview)——startup <500ms, package <50MB, three-platform native WebView.
2. Kernel must remain pure Python——bottleneck is LLM API (500ms-5s), not computation (microsecond level), must not introduce Rust/C++.
3. Territory must be divided by layer——Agent A (HTTP layer: routes/params/middleware/auth/i18n), Agent B (business layer: pages/services/visa/cache/config), Agent C (quality and security layer: tests/security/nomos_mcp/memories/scripts).
4. L3 must use a pure rule engine ~100 lines of Python——Task Card already structures intent, must not introduce LLM for routing.
5. MVP scope must be limited to 4 days——Intent Card + L3 + 1 Agent + 5 Tools + Dual Ring Panel + pywebview window.
6. Development phase uses `python run.py` (Flask browser debugging), production phase uses `python run.py --gui` (Praxis window), no need to maintain two APIs.

## Specifications

- P0 prerequisite: `pip install pywebview` passes on Python 3.14, otherwise fall back to tkinter
- MVP 5 tools: read_file(0), grep_search(0), replace_string_in_file(1), run_in_terminal(1), read_fingerprint(0)
- MVP does not require: multi-agent approval, multi-unit, Ring Ω, desktop packaging
- Post-MVP P1 prioritization: (1) Validate 1 Agent completing real tasks (2) Second Agent + cross-territory approval (3) Desktop packaging
- Praxis integration path (Issue #6, Scheme C): MVP stage Praxis runs independently, imports existing code directly via `import nomos`, not via HTTP
- P0 prerequisite: `pip install pywebview` verified on Python 3.14
- P1 candidates: Validate 1 Agent completing real tasks, Second Agent + approval flow, Desktop packaging (in this order)
- Dev/production coexistence: Development phase `python run.py` → Flask browser debugging, production phase `python run.py --gui` → Praxis window
- 5 tools specified: read_file(0)/grep_search(0)/replace_string_in_file(1)/run_in_terminal(1)/read_fingerprint(0)

## Exclusions

- Rust Tauri / C++ Qt / Electron: replaced by pywebview (Rust = dual language maintenance, Qt > 50MB package, Electron > 100MB package and > 2s startup)
- Rust/C++ rewrite of kernel parts: excluded (only bottleneck is LLM API, not computation)
- Territory by domain (Scheme B) or manual declaration (Scheme C): excluded (by-layer scheme has the least cross-territory approvals ~15-20%)
- L3 using small or large model: excluded (structured intent doesn't need NLP understanding)
