---
name: api-fuzz-tester
description: "Fuzz API surfaces with property-based tests and boundary payloads, catching unhandled exceptions, 500s, and unbounded-input DoS from client data."
---

# API Fuzz Tester

## 1. Scope & Objective
- Break APIs on purpose: property-based fuzzing, boundary and malformed-input payloads, and a hard rule that client input can never produce an unhandled 500.
- In scope: fuzz properties, boundary tables, malformed corpora, persistent failure corpora, bounded-parse verification.
- Out of scope (delegate): load/throughput → `load-stress-testing`; contract shape → `openapi-contract`.

## 2. Trigger Conditions
- Commands: "fuzz the API", "the endpoint 500s on weird input", "add property tests for X", "can this parser be abused".
- Intent patterns: new endpoints; parser/serializer additions; pre-release hardening; any observed 500 from client data.
- Orchestration tags: `test:fuzz`, `sec:fuzz`, `gate:hardening`.

## 3. Core Directives & Standards
1. **Client input must never cause an unhandled exception → 500.** That is a failure, full stop; "the client sent bad data" is not a defense — the server owns its error boundary.
2. **Properties, not just examples:** for each input domain, a checkable property (e.g., "parse(sanitize(x)) never throws; response is 4xx, never 5xx; invariants hold"); property-based frameworks (Hypothesis, fast-check, quickcheck).
3. **Boundaries are explicit:** 0, -1, MAX_INT, empty string, whitespace, huge payloads (10 MB class), unicode (RTL, emoji, null bytes, homoglyphs), malformed JSON, wrong types, missing/extra fields.
4. **Corpora persist:** every captured failing input is saved to a regression corpus and replayed on every run — a found bug that isn't pinned is found again.
5. **Boundedness is verified:** malformed input must not trigger unbounded parse time or memory (the OOM is a DoS vector); parse timeouts/size limits are asserted.

## 4. Execution Workflow
1. **Intake & Analysis:** List endpoints and their input domains; state the trust assumptions (what the client may/may not send); pick the properties that must hold per endpoint.
2. **Implementation:** Write property tests per endpoint; build the boundary table; assemble the malformed corpus (generated + hand-crafted); run fuzzing within a time/case budget; capture every failure into the persistent corpus.
3. **Validation:** 0 unhandled 500s from client input across the fuzz run (report attached); every captured failure fixed and present in the regression corpus; boundedness checks pass (parse time/memory bounded on malformed input); corpus size tracked.

## 5. Antipatterns & Prohibited Behaviors
- "Fuzzing" that only tries happy-path variants (that's testing, not fuzzing).
- "It works in Postman" as evidence of robustness.
- 500s classified as "client error, client's problem".
- Ephemeral corpora: failures fixed but not saved, so they regress silently.
- Unbounded inputs accepted (10 GB JSON, 10⁶ nesting depth) — robustness theater until the OOM.

## 6. Definition of Done & Quality Guardrails
- Property suite committed and running in CI (auto-executed every PR).
- Fuzz run report: 0 client-input 500s; boundary table covered.
- Persistent corpus grows with every found bug; all corpus cases green.
- Max request size and parse-time bounds documented and asserted by tests.
