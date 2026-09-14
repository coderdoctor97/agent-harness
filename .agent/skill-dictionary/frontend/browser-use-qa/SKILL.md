---
name: browser-use-qa
description: "Run headless-browser QA against the live app: scripted user journeys, DOM snapshot assertions, console/network error capture, and screenshot evidence."
---

# Browser-Use QA (Headless E2E Smoke)

## 1. Scope & Objective
- QA the running application end-to-end in a headless browser: script critical user journeys, assert on DOM state, capture console and network errors as pass/fail signals, and produce screenshot evidence.
- In scope: smoke and regression checks of P0 flows against a deployed or local environment.
- Out of scope (delegate): isolated component testing → `playwright-component-testing`; load/stress → `load-stress-testing`; visual design review → `web-design-reviewer`.

## 2. Trigger Conditions
- Commands: "QA the app", "verify the <flow> still works", "run a smoke check after deploy".
- Intent patterns: post-deploy verification, release gating, "did this PR break the main flows".
- Orchestration tags: `qa:e2e`, `qa:smoke`, `gate:release`.

## 3. Core Directives & Standards
1. **Deterministic starts:** fresh browser context, seeded fixtures, third-party calls intercepted — no flaky external dependencies inside QA.
2. **Assert on DOM state first** (roles, text, visibility) with auto-waiting expectations; screenshots are evidence, not primary assertions.
3. **Every run captures console errors and failed network requests;** any unexplained console error or 5xx on the flow's own calls fails the run.
4. **One journey = one script with named steps** (navigate → act → assert); a failing step produces a self-explanatory artifact (screenshot + DOM snapshot + console log).
5. **Repeatable suites:** 5/5 consecutive green runs before a suite counts as stable.

## 4. Execution Workflow
1. **Intake & Analysis:** List the P0 journeys; define each happy path plus one failure path; identify external calls that must be intercepted.
2. **Implementation:** Script each journey; seed fixtures; wire interception; assert DOM at every step boundary; screenshot at each step for the artifact trail.
3. **Validation:** 5 consecutive runs all green; inject a deliberate failure once and confirm the artifacts (screenshot + snapshot + log) explain it without extra context; total suite runtime under 10 minutes.

## 5. Antipatterns & Prohibited Behaviors
- `sleep(2000)`-style waits (use auto-waiting assertions).
- Screenshot-only assertions ("looks right to me").
- Running against unseeded shared environments (state contamination between runs).
- Ignoring console warnings that persist across the whole run.
- Suites that "pass" while asserting almost nothing (e.g., HTTP 200 checks only).

## 6. Definition of Done & Quality Guardrails
- Smoke suite covers 100% of P0 journeys (journey list maintained in the suite README).
- 5/5 consecutive green runs; suite runtime under 10 minutes.
- Failure artifact verified self-explanatory (screenshot + DOM snapshot + console log) via one deliberate fault injection.
- Console/network error budget: 0 unexplained errors in green runs.
