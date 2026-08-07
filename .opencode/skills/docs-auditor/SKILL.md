---
name: docs-auditor
description: Use when auditing comments and docstrings — scans for CJK residue (excluding i18n data), missing module docstrings, and missing class/function docstrings per Praxis comment conventions.
---

## Overview

Documentation and comment auditor for the Praxis codebase. Enforces the comment
conventions in AGENTS.md: English is the baseline language for all comments,
docstrings, and module/class/function docs; CJK is only allowed inside
intentional data (i18n translation dicts, injection-detection keywords). The
goal is 0 CJK residue in code comments.

## Workflow

### 1. Scope the Audit
- If a diff/commit range is given, audit only the changed `.py` files.
- Otherwise scan `src/` (all layers L1-L5) and report the worst offenders.
- Exclude `locales/`, `config/skills/`, and i18n translation data.

### 2. CJK Residue Scan
For each target `.py` file:
- Find CJK characters (Unicode ranges U+4E00–U+9FFF, U+3400–U+4DBF, U+F900–U+FAFF)
  appearing inside `#` comments or `"""` docstrings.
- Ignore CJK inside string literals that are intentional data (i18n dicts,
  injection-detection keywords).
- Report file:line with the offending snippet.

### 3. Module Docstring Check
- Every module must have a module-level docstring (one-liner explaining purpose).
- Flag `.py` files under `src/` whose first non-comment statement is not a
  docstring (exclude `__init__.py` files that are intentionally empty, and
  `tests/`).

### 4. Class Docstring Check
- Every public class (dataclasses included) must have a class docstring
  describing its role.
- Flag public classes (no leading `_`) lacking a docstring.

### 5. Public Function Docstring Check
- Public functions require a docstring (what it does + returns).
- Simple getters/setters and private helpers (`_*`) may skip.
- Flag public functions (no leading `_`) lacking a docstring.

### 6. Report
Output a structured summary:
- `[CJK]` — file:line with CJK in comment/docstring
- `[MODULE]` — file missing module docstring
- `[CLASS]` — file:line, class missing docstring
- `[FUNC]` — file:line, function missing docstring

End with a short verdict: PASS (0 residue + no missing docstrings) or FAIL
with a count per category. Never edit files — report only.
