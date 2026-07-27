---
Fonds: DESIGN
File: guide
Item: 001
Type: Implementation
Date: 2026-07-22
Timestamp: 2026-07-22T19:00
Author: L3
Keywords: [NOMOS, Praxis, quickstart, guide]
Relations: [ARCHIVE-design-001]
Debts: []
---

# NOMOS Praxis Quickstart Guide

> 5 minutes from zero to your first intent execution.

## Prerequisites

- Python 3.11+
- This repository is cloned locally

## Startup

```bash
# Start Praxis GUI from the project root
python run.py --gui
```

Wait for the pywebview window to appear (first launch may take a few seconds to load the Flask backend).

## First Intent

In the Chat input box on the right side of the window, enter:

```
Modify database connection configuration
```

Flow:
1. L3 engine parses intent → identifies domain `app/config`
2. Routes to Agent B (business layer)
3. Shows task preview card, click **Confirm**
4. Agent B executes: `read_file` → `grep_search` → `replace_string_in_file`
5. Left transaction area generates task card
6. Center editor shows file change Diff
7. Bottom panel updates execution logs and gate status in real time

## Verification

- Window title bar shows `Kernel Online` (green dot)
- Agent stream bar shows execution progress
- Bottom status bar shows Agent reputation score and PID

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| White screen | Flask backend not ready | Wait for `Running on 127.0.0.1:5007` in terminal |
| Parse failure | L3 engine did not recognize intent | Try a more explicit expression, e.g. "change debug to true in config.py" |
| Execution blocked | GateChain G3 territory check | Confirm Agent has territory permission for the target file |
