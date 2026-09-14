---
name: schema-compatibility
description: "Enforce backward-compatible evolution of event and protocol schemas (Protobuf, JSON, Avro) with CI compat checks and dual-publish migrations."
---

# Schema Compatibility

## 1. Scope & Objective
- Keep event buses and protocol contracts evolvable without breaking producers or consumers: compatibility rules, CI checks, and migration mechanics for breaking changes.
- In scope: schema evolution rules, compat tooling in CI, versioned topics, dual-publish migrations.
- Out of scope (delegate): REST API contracts → `openapi-contract`; database schema → `db-migrations`.

## 2. Trigger Conditions
- Commands: "add a field to the event", "can we remove this field", "new consumer for X topic", "the schema changed and consumers broke".
- Intent patterns: any protocol/event schema change; new producers or consumers onboarding; consumer breakage reports.
- Orchestration tags: `schema:evolve`, `schema:compat`, `gate:schema`.

## 3. Core Directives & Standards
1. **Additive changes by default:** new fields optional with safe defaults; consumers must read old messages, producers write old + new fields during the window; in-place changes pass both BACKWARD (new reads old) and FORWARD (old reads new) checks.
2. **Protobuf discipline:** field numbers are never reused or deleted (mark `reserved`); no type changes in place; `optional` over `required` for new fields.
3. **JSON discipline:** new fields optional + defaulted; no type changes; no silent field renames (a rename is a remove + add = breaking).
4. **Breaking changes go through a versioned path:** new topic/channel (v2), dual-publish during migration, consumer migration plan with dates, and deprecation of the old version — never an in-place breaking swap.
5. **Compat checks run in CI** (buf breaking, avro-compat, jsonschema diff, or equivalent) and block merges — "it's just a field, no one uses it" without usage evidence is not a review.

## 4. Execution Workflow
1. **Intake & Analysis:** Diff the schema change (added/changed/removed fields); inventory all producers and consumers of the schema (with their versions and consumer lag); classify additive vs breaking.
2. **Implementation:** Additive: apply with defaults, pass CI compat checks. Breaking: create the v2 schema, dual-publish, write the consumer migration plan (who, when, verification), schedule the old-version deprecation.
3. **Validation:** CI compat checks green (BACKWARD + FORWARD for in-place); consumer smoke test on old-schema messages; during dual-publish: both versions flowing, message counts continuous across the cutover (no silent drops); consumer inventory updated.

## 5. Antipatterns & Prohibited Behaviors
- Field number reuse in Protobuf (the classic silent-corruption bug).
- "It's just a field, no one uses it" without a consumer-usage check.
- In-place type changes or renames.
- V2 topics with no migration or deprecation plan (two schemas forever).
- Running the compat check after deploy instead of in CI.

## 6. Definition of Done & Quality Guardrails
- CI compat check (BACKWARD + FORWARD) green for the change.
- Consumer inventory updated with versions and migration dates.
- Breaking changes: dual-publish running, deprecation schedule documented, message-count continuity verified across cutover.
- Schema versioned and stored; the change's classification (additive/breaking) recorded in the PR.
