---
name: debug-regression-bisect
description: "Localize bugs systematically: deterministic reproduction, single-variable hypothesis testing, git bisect for regressions, and a regression test that fails without the fix."
---

# Debug & Regression Bisect

## 1. Scope & Objective
- Find root causes, not symptoms: reproduce the bug, bisect the regression, test hypotheses one variable at a time, and ship the fix with a regression test.
- In scope: stack-trace diagnosis, reproduction, `git bisect`, instrumentation, and the final fix + test.
- Out of scope (delegate): performance root causes → `performance-benchmarking`; production incident process → `incident-postmortem-rca`; flaky test mechanics → `flaky-test-isolator`.

## 2. Trigger Conditions
- Commands: "it's broken", "this is a regression", "here's the stack trace", "X stopped working after Y".
- Intent patterns: any bug report; a failing test; behavior that changed between known-good states.
- Orchestration tags: `debug:repro`, `debug:bisect`, `fix:regression`.

## 3. Core Directives & Standards
1. **Reproduce before fixing** — a deterministic repro (steps or failing test) is the entry ticket; "I think it's the cache" without a repro is not debugging.
2. **One variable at a time.** Each experiment changes exactly one thing; conclusions attach to evidence, not vibes.
3. **Regressions get a bisection:** `git bisect` on a repro (or state bisection for non-git state) — never "somewhere in the last month" guessing.
4. **Read stack traces bottom-up to the first frame in your code** — the throw site is usually the messenger, not the cause; the root cause sits where an assumption broke, higher in the call chain.
5. **Every fix ships a regression test** that fails on the pre-fix code and passes after — verified in both directions.

## 4. Execution Workflow
1. **Intake & Analysis:** Capture the stack trace, exact repro steps, last-known-good state, and environment differences; turn the repro into a failing test where feasible.
2. **Implementation:** Bisect to the offending commit/change; instrument the suspected boundary (log/assert); verify the hypothesis with a single-variable experiment; implement the minimal correct fix; remove all debug instrumentation.
3. **Validation:** Repro steps now succeed; regression test fails on old code and passes on new; adjacent flows (things sharing the changed path) spot-checked; no debug code left in the diff.

## 5. Antipatterns & Prohibited Behaviors
- "Works on my machine" as a conclusion (environment is part of the diagnosis).
- Multi-variable "fixes" (change five things, it works, unknown which mattered).
- Deleting or weakening the failing test to go green.
- Fixing without a repro (fixes by luck, regressions guaranteed).
- Adding a retry to hide a race (proper fix belongs in `flaky-test-isolator`).

## 6. Definition of Done & Quality Guardrails
- Root cause documented: what broke, why, and the evidence (trace, bisect output, experiment log).
- Regression test committed and verified failing pre-fix / passing post-fix.
- Original repro steps succeed; instrumentation removed from the diff.
- Adjacent-flow spot check recorded (what else shares the changed path).
