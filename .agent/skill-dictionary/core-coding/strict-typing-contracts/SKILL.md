---
name: strict-typing-contracts
description: "Enforce strict typing (TS strict, mypy --strict): zero unannotated any, exhaustive narrowing, runtime validation at every trust boundary, and no cast-to-silence."
---

# Strict Typing Contracts

## 1. Scope & Objective
- Make the type system the primary correctness instrument: strict compiler configuration, elimination of `any`/`Any`, exhaustive narrowing, and runtime validation at every trust boundary.
- In scope: type architecture, boundary validation, compiler/linter gate config, migration of loose code.
- Out of scope (delegate): API contract shape → `openapi-contract`; review verdicts → `pr-code-reviewer`.

## 2. Trigger Conditions
- Commands: "the types are lying", "there's an `any` in this diff", "add strict typing", "TS errors after the upgrade".
- Intent patterns: new modules; external data (API/env/file) being consumed; repeated runtime surprises that types should have caught.
- Orchestration tags: `types:strict`, `types:migrate`, `gate:types`.

## 3. Core Directives & Standards
1. **Strict mode is non-negotiable:** `strict: true` (TS) / `mypy --strict` (Python) project-wide; no project-level disables; `noUnusedLocals`/`noUnusedParameters` on.
2. **Zero unannotated `any`/`Any`:** use `unknown` (or `Any` with an explicit, documented boundary) and narrow deliberately; every remaining `any` is in a versioned allowlist with a reason.
3. **Exhaustive handling:** union/enum switches include a `never` exhaustiveness check — a new variant is a compile error, not a silent miss.
4. **Runtime validation at every trust boundary** (API responses, env vars, files, IPC): zod/valibot/pydantic schemas, with the parsed type flowing inward; internal code trusts its types, boundaries don't trust anyone.
5. **No cast-to-silence:** `as`/type-assertions that silence a mismatch are prohibited — fix the shape; no blanket `@ts-ignore`/`# type: ignore` without a reason + tracking.

## 4. Execution Workflow
1. **Intake & Analysis:** Type audit: count `any`/`Any`, casts, and suppressions; list every trust boundary (where external data enters); check current strictness config.
2. **Implementation:** Enable/complete strict config; migrate loose code (unknown → narrow); add boundary validators with tests; add exhaustiveness checks; build the `any` allowlist for genuine third-party gaps.
3. **Validation:** `tsc --noEmit` / `mypy` reports 0 errors; grep audit: `any`/`Any` outside the allowlist = 0, blanket suppressions = 0; mutation check — deliberately change a boundary field's type and confirm the compile or boundary test catches it.

## 5. Antipatterns & Prohibited Behaviors
- `as any` / `as unknown as T` to make a mismatch go away.
- Blanket `@ts-ignore` / `# type: ignore` (one suppressions per line, with reasons, or none at all).
- Hand-maintained "parallel types" that drift from runtime reality instead of generated or boundary-validated types.
- Boolean flag pairs (`isLoading` + `hasError`) where a discriminated union state machine belongs.
- Turning strict mode off per-file instead of fixing the file.

## 6. Definition of Done & Quality Guardrails
- Strict compile pass: 0 errors (CI-enforced).
- `any`/`Any` audit: 0 outside the documented allowlist; suppression audit: 0 blanket suppressions.
- Every trust boundary has a validator with pass/fail tests.
- Mutation check verified: a deliberate type break is caught at compile time or by a boundary test.
