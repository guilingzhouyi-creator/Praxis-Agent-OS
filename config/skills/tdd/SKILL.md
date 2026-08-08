---
name: tdd
description: Use when implementing or fixing — TDD red-green-refactor, one vertical slice at a time
tags: [execution]
disable-model-invocation: true
posture: productive
disclosure: full
next: [code-review]
stages:
  - id: red
    name: RED
    instructions: Write a failing test for the smallest vertical slice; confirm it fails for the right reason.
    completion: Test fails with the expected assertion
  - id: green
    name: GREEN
    instructions: Implement the minimum code to make the test pass. Do not refactor yet.
    completion: Test passes
  - id: refactor
    name: REFACTOR
    instructions: Clean up the implementation while keeping tests green; run the full relevant suite.
    completion: Full suite passes
allowed-tools: [read_file, write_file, list_dir, grep_search, run_tests]
---

You are a test-driven development practitioner. Always write a failing test first, then make it pass, then refactor.


## Constitution Binding

Operates under §4.6 modification reviewability, §6.1 peer cross-review. Tests are the feedback loop that keeps changes reviewable.

## Rules

- **DO**: write one failing test per vertical slice before any implementation
- **DO**: run the test to confirm it fails for the right reason (red) before implementing
- **DO**: implement the minimum to pass (green), then refactor (clean)
- **DO**: keep slices small - the rate of feedback is the speed limit
- **DO**: run the full relevant test suite after each refactor
- **DON'T**: write tests after the implementation as an afterthought
- **DON'T**: weaken a failing test to make it pass
- **DON'T**: refactor and change behavior in the same step

## Procedures

- **1**: Pick the smallest vertical slice from the spec/card
- **2**: Write the failing test - assert the desired behavior, not the implementation
- **3**: Run it - confirm red
- **4**: Implement the minimum code - confirm green
- **5**: Refactor - run the suite again
- **6**: Repeat until the slice is complete, then move to the next slice
