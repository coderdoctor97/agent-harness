---
name: playwright-component-testing
description: "Mount and verify UI components in isolation with headless browser tests: real-DOM interaction, role-based selectors, and reviewed visual snapshots."
---

# Playwright Component Testing

## 1. Scope & Objective
- Test UI components in isolation in a real browser DOM using Playwright Component Testing (`@playwright/experimental-ct-react`, or the Vue/Svelte equivalents): rendered states, event handling, a11y behavior, and visual regression.
- In scope: component-level happy/edge/error paths, keyboard interaction, snapshot baselines.
- Out of scope (delegate): full-application user journeys → `browser-use-qa`; pure logic unit tests → `tdd-test-runner`; a11y rule conformance → `accessibility-a11y` (this skill executes the a11y assertions inside components).

## 2. Trigger Conditions
- Commands: "test the <Component>", "add component tests for X", "visual regression on this widget".
- Intent patterns: any PR adding or changing a UI component's public behavior must land component tests in the same PR.
- Orchestration tags: `test:component`, `test:visual`, `gate:components`.

## 3. Core Directives & Standards
1. **Real DOM, real dependencies.** Mount components with real context/store wiring; fake only the network (MSW or route interception). Never assert on framework internals.
2. **Selectors by role, label, or `data-testid` only.** CSS class selectors are prohibited — classes are implementation details.
3. **Assert user-observable behavior** (text, role, visibility, attributes, emitted events), never component state or hook internals.
4. **Visual snapshots with review.** Baselines must be human-reviewed before commit; pixel-diff tolerance ≤ 0.05; every snapshot renders the component alone (fixed viewport, seeded data).
5. **Speed discipline.** One behavior per test; each test < 5s; the full component suite < 2 minutes.

## 4. Execution Workflow
1. **Intake & Analysis:** List the component's public API (props, events), its states (default/loading/empty/error/disabled), and its a11y contract (roles, names, focus behavior).
2. **Implementation:** Write one test per state and per interaction: render → interact (mouse and keyboard paths) → assert. Every interactive component gets at least one keyboard-only path.
3. **Validation:** Suite green from a clean install; 5 consecutive runs with zero flakes; snapshot diffs reviewed and committed alongside the change; CI runs the suite on every PR touching the component.

## 5. Antipatterns & Prohibited Behaviors
- Selecting elements by private class names or by `data-testid` that duplicates the state machine.
- `waitForTimeout` as a synchronization mechanism (use auto-waiting assertions instead).
- Committing snapshot baselines without reviewing the diff.
- Reading component state directly (hook internals) to verify behavior instead of the DOM.
- Skipping keyboard tests for interactive widgets because the mouse path works.

## 6. Definition of Done & Quality Guardrails
- 100% of public states and interactions covered; coverage matrix documented in the test file header.
- 5/5 consecutive green runs (flake check) and suite runtime under 2 minutes.
- Snapshot baselines committed only with reviewed diffs; zero unexplained pixel deltas.
- At least one keyboard-path test exists for every interactive component.
