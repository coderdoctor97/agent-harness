---
name: form-management
description: "Implement forms with React Hook Form plus schema validation (Zod/Valibot), correct error UX, and zero unnecessary re-renders."
---

# Form Management (RHF + Schema Validation)

## 1. Scope & Objective
- Build client-side forms: field registration, validation, error display, submission semantics, and re-render discipline using React Hook Form (RHF) with a schema validator (Zod or Valibot).
- In scope: forms of any size, including dynamic field lists and cross-field rules.
- Out of scope (delegate): server-side validation contracts → `openapi-contract`; a11y of form controls → `accessibility-a11y`.

## 2. Trigger Conditions
- Commands: "build a form for X", "migrate this form to RHF", "the form re-renders on every keystroke".
- Intent patterns: new CRUD surfaces, settings/onboarding/checkout flows, form performance complaints.
- Orchestration tags: `ui:form`, `perf:form`.

## 3. Core Directives & Standards
1. **One source of validation truth:** a Zod/Valibot schema with the matching RHF resolver — never re-implement rules inline in components.
2. **Uncontrolled by default:** `register()` for plain fields; `useController`/`useWatch` only when derived UI genuinely needs the value.
3. **Zero re-renders on typing:** no `value` props on plain inputs, no form-level `setState` per keystroke; verify with React Profiler, not by feel.
4. **Server errors map to fields:** `setError` with precise field targets and human-readable messages; no field- or form-level error is silently dropped.
5. **Submission is guarded:** submit disabled or gated on `isSubmitting`; double-Enter/double-click produces exactly one submission (or a client idempotency key).

## 4. Execution Workflow
1. **Intake & Analysis:** Inventory fields, rules (per-field and cross-field), the server error contract (shape of 422 responses), and submission semantics (idempotent? partial success?).
2. **Implementation:** Schema first (with its own tests), then form wiring, then error display (on blur and on submit), then the submit handler with server-error mapping. Dynamic lists via `useFieldArray`.
3. **Validation:** Profiler trace while typing shows only the affected subtree re-rendering; validation fires on blur (field) and on submit (all fields); a server-error round-trip test (422 → correct field message) passes; keyboard tab order and label association verified.

## 5. Antipatterns & Prohibited Behaviors
- Controlled inputs for every field "to make reasoning easier" (re-render tax per keystroke).
- Duplicating validation logic in components alongside the schema.
- Hiding the form on submit instead of showing a submitting state (state loss on error).
- Treating 422 as one generic banner instead of field-level errors.
- Adding fields that exist only in `defaultValues` but not in the schema.

## 6. Definition of Done & Quality Guardrails
- Profiler evidence: 0 unrelated component re-renders while typing in any field.
- Schema tests: every rule has a pass case and a fail case.
- Automated tests exist and are green for the happy path and the server-error path.
- All fields validate on blur and on submit; cross-field rules verified by tests.
- Form control labels and a11y checked (full conformance delegated to `accessibility-a11y`).
