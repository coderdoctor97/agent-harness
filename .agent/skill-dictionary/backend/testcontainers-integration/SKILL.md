---
name: testcontainers-integration
description: "Build ephemeral, containerized integration test fixtures (databases, caches, brokers) with per-test isolation and deterministic data."
---

# Testcontainers Integration

## 1. Scope & Objective
- Provide real, ephemeral dependencies for integration tests using Testcontainers (or equivalent): databases, caches, brokers — with strict isolation between tests and guaranteed cleanup.
- In scope: container fixtures, schema setup, data seeding, suite determinism.
- Out of scope (delegate): unit test strategy → `tdd-test-runner`; full-browser E2E → `browser-use-qa`.

## 2. Trigger Conditions
- Commands: "the tests need a real DB", "the mock doesn't behave like Postgres", "integration tests are order-dependent".
- Intent patterns: new service with stateful dependencies; flaky tests traced to shared fixtures; mock/prod divergence.
- Orchestration tags: `test:integration`, `test:fixtures`, `gate:integration`.

## 3. Core Directives & Standards
1. **Real binaries for the dependency under test** — no driver-level mocks of the database itself; the whole point is real behavior.
2. **Zero cross-test contamination:** each test (or test class) gets its own instance or transactionally rolled-back state; no shared mutable fixtures.
3. **Reuse is opt-in and CI-only:** container reuse modes never default on for local runs (stale state is a classic flake source).
4. **Fast fixtures:** per-class containers where per-test startup is too expensive; startup budget < 30s for the fixture; data seeding is declarative (fixture files), not inline test bodies.
5. **Guaranteed teardown:** containers and volumes are always cleaned up; a leaked container after a failed run is a test-infrastructure bug.

## 4. Execution Workflow
1. **Intake & Analysis:** List stateful dependencies; inventory current mocks and their divergence incidents; check current suite for order dependence (shuffle once to find out).
2. **Implementation:** Build a generic container factory (per-dependency); per-test schema setup; declarative seed fixtures; integration test slices using them; wire random-order execution.
3. **Validation:** Suite passes 5 consecutive runs in random order; `docker ps` shows 0 leftover containers/volumes after runs; integration slice time within budget (reported per run).

## 5. Antipatterns & Prohibited Behaviors
- A shared container with global state "for speed" (the #1 flake factory).
- Mocking the database driver itself (defeats the purpose).
- Seeding data inline in test bodies (untestable, unshareable, drifts).
- Swallowing connection failures so tests pass against nothing.
- Publishing container ports to the host when the test only needs the network.

## 6. Definition of Done & Quality Guardrails
- Suite green 5/5 in randomized order (run log attached).
- 0 leftover containers or volumes after any run (verified by inspection).
- Fixture startup within budget; integration slice time reported and tracked.
- Seeding is declarative and reused across tests (no inline data setup).
