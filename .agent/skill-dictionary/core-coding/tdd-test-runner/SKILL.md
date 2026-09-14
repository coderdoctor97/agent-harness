---
name: tdd-test-runner
description: "Run test-first development loops: failing tests written first, red-green-refactor discipline, fixtures over mocks, and boundary-case coverage."
---

# TDD Test Runner

## 1. Scope & Objective
- Drive implementation test-first: write the failing test, make it pass with minimal code, then refactor — with explicit boundary/edge-case coverage and fixtures over mocks.
- In scope: unit and integration test authoring for new logic and bug fixes; regression tests before fixes.
- Out of scope (delegate): flaky test remediation → `flaky-test-isolator`; containerized fixtures → `testcontainers-integration`.

## 2. Trigger Conditions
- Commands: "implement X" (new logic), "fix this bug" (regression test first), "add tests for Y", "prep this refactor".
- Intent patterns: any new behavior; any bug report; any refactor needing safety net.
- Orchestration tags: `test:write`, `test:regression`, `tdd:loop`.

## 3. Core Directives & Standards
1. **Failing test before production code** for new logic — the test must fail for the right reason (verify by reading the failure, not just seeing red). No waivers without an explicit, recorded exception.
2. **One behavior per test** in Arrange-Act-Assert shape; test names read as specifications ("`rejects empty email`", not "`testEmail2`").
3. **Boundaries are mandatory** for every numeric/string/collection input: 0, 1, N, negative, max/overflow, empty, and unicode/edge encodings.
4. **Fixtures over mocks:** real objects for everything except true system boundaries (network, clock, filesystem where permitted); mock only where isolation is genuinely needed.
5. **Speed:** unit tests < 2s each; no live network or real LLM calls in unit tests (deterministic fakes only).

## 4. Execution Workflow
1. **Intake & Analysis:** Translate the requirement into a behavior list with boundary cases (this list is the test plan); identify what is a true system boundary.
2. **Implementation:** RED — write the failing test(s) and confirm the failure reason; GREEN — minimal code to pass; REFACTOR — improve structure while staying green; repeat per behavior.
3. **Validation:** Mutation sanity check — deliberately break the implementation and confirm the test catches it; full suite green; every behavior in the plan has a named test; boundary matrix complete per input type.

## 5. Antipatterns & Prohibited Behaviors
- Writing tests after the code to match whatever the code does (tests as after-the-fact documentation).
- Testing implementation details (private methods, internal state) instead of behavior.
- Tautological assertions (`assertEqual(x, x)`).
- Skipping tests "because it's too hard to test" (a smell the design is wrong, not the test).
- 50-line tests with ten asserts (one failure buries nine).

## 6. Definition of Done & Quality Guardrails
- Every new behavior has a test that demonstrably fails without the implementation (evidence: mutation sanity check or pre-implementation red run).
- Boundary matrix covered per input type (documented in the test file).
- Full suite green; unit test runtime within budget.
- For bug fixes: the regression test fails on the old code and passes on the fix (verified both ways).
