---
name: flaky-test-isolator
description: "Diagnose and eliminate flaky tests: real time, shared state, order dependence, and race conditions — fixed at the root, never hidden by retries."
---

# Flaky Test Isolator

## 1. Scope & Objective
- Find and eliminate non-deterministic test failures: diagnose the source of flakiness, fix the root cause, and prove determinism — with quarantine only as a tracked, expiring intermediate state.
- In scope: flake diagnosis, root-cause fixes, quarantine management, determinism proof.
- Out of scope (delegate): writing new tests → `tdd-test-runner`; performance timing issues → `performance-benchmarking`.

## 2. Trigger Conditions
- Commands: "the test fails but passes locally", "CI is flaky", "this test failed then passed on retry".
- Intent patterns: intermittent CI failures; retry-and-pass records; "works on my machine" test disputes.
- Orchestration tags: `test:flake`, `test:determinism`, `gate:flakes`.

## 3. Core Directives & Standards
1. **A flaky test is a bug** — in the test or the code — not a CI nuisance; it gets root-caused like any defect.
2. **Retries are not fixes:** `retry: 3` masking a flake is prohibited; quarantine is allowed only with a ticket, an owner, and an expiry date.
3. **The five classic causes are checked in order:** real time (→ fake/monotonic timers), shared state (→ per-test isolation), order dependence (→ randomized runs), async races (→ deterministic awaits, no sleeps), unseeded randomness/network (→ fixed seeds, MSW-style fakes).
4. **Determinism is proven, not claimed:** the fixed test passes 50/50 in isolation *and* in the suite, including randomized order.
5. **Fix the assertion's cause, not the assertion:** widening an assertion to paper over a race is prohibited; the behavior (or the test's coupling) changes deliberately.

## 4. Execution Workflow
1. **Intake & Analysis:** Collect failure evidence: logs, which runs/order/machines fail, retry-and-pass patterns; run the test N times (e.g., 50) to reproduce; run the suite shuffled to expose order dependence.
2. **Implementation:** Isolate the cause (binary-search the test set; swap real→fake for time/network one at a time); fix the root cause (fake timers, per-test isolation, deterministic awaits, seeded randomness); if quarantine is unavoidable, register it with ticket + owner + expiry.
3. **Validation:** 50 consecutive green runs (isolation + suite, evidence log attached); 10 randomized-order runs green; the quarantine registry entry closed (or none created); flake metric for the test = 0.

## 5. Antipatterns & Prohibited Behaviors
- `retry: 3` (or any retry) as the "fix".
- Deleting the flaky test ("it wasn't testing anything important" — it was testing something, and now it's untested).
- `sleep()` as a synchronization mechanism.
- "Works on my machine" as the closing word on a flake.
- Quiet, permanent quarantines (no ticket, no owner, no expiry — the flake becomes folklore).

## 6. Definition of Done & Quality Guardrails
- Root cause documented from the five-cause list (time / state / order / race / external) with evidence.
- 50/50 green in isolation and in-suite (run log attached); 10 randomized-order runs green.
- Quarantine registry: 0 untracked entries; any used entry has ticket + owner + expiry.
- Flake metric for the test is 0 over the verification window.
