---
name: openapi-contract
description: "Manage API contracts OpenAPI 3.1-first: lint, generate clients/servers, run conformance tests, and block API drift in CI."
---

# OpenAPI Contract-First

## 1. Scope & Objective
- Own the API contract: author and evolve OpenAPI 3.1 specifications, lint them, generate code from them, and enforce conformance so client and server never drift.
- In scope: spec authoring, linting, codegen wiring, conformance/drift CI gates, versioning decisions.
- Out of scope (delegate): endpoint implementation logic → owning backend workstream; load behavior → `load-stress-testing`.

## 2. Trigger Conditions
- Commands: "update the API spec for X", "we need a new endpoint", "the client and server disagree about Y".
- Intent patterns: any PR changing the API surface; new consumers onboarding; contract complaints.
- Orchestration tags: `api:contract`, `api:codegen`, `gate:contract`.

## 3. Core Directives & Standards
1. **The spec is the source of truth.** Clients (and server stubs) are generated from it; hand-maintained client models that diverge are defects.
2. **OpenAPI 3.1** (JSON Schema dialect): every operation defines request schema, success response, error responses (400/404/409/500 as applicable), and at least one example.
3. **No free-form objects:** `additionalProperties: false` on typed bodies; enums over magic strings; every field documented.
4. **Drift is impossible by construction:** CI runs (a) spectral lint, (b) breaking-change diff on the spec, (c) conformance tests (Schemathesis/dredd or equivalent) against a running server.
5. **Versioning policy is explicit:** additive changes = same version; breaking changes = new version with a documented deprecation window.

## 4. Execution Workflow
1. **Intake & Analysis:** Diff the requested change against the current spec; classify additive vs breaking; identify affected consumers.
2. **Implementation:** Update the spec; regenerate clients and server stubs; extend conformance tests for new/changed operations.
3. **Validation:** Spectral lint: 0 errors; breaking-change diff clean (or version bump documented with deprecation); conformance suite green against a running instance; generated code committed and CI-verified in sync.

## 5. Antipatterns & Prohibited Behaviors
- "I'll update the spec later" — code changes merged without the spec change.
- `anyOf`-everything schemas that describe nothing.
- Versioning by query parameter instead of a declared version path/header.
- Undocumented error bodies (the client has no way to handle failures).
- Manually editing generated client code.

## 6. Definition of Done & Quality Guardrails
- Spec lint clean (0 errors; warnings triaged).
- Breaking-change tool reports no unannounced breaks; version policy followed.
- Conformance suite green (every operation exercised, including error paths).
- Generated artifacts in sync — CI fails if spec and generated code disagree.
