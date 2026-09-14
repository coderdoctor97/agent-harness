---
name: db-migrations
description: "Author and apply safe, non-destructive DDL migrations with expand-migrate-contract sequencing, bounded lock times, and tested rollbacks."
---

# Database Migrations

## 1. Scope & Objective
- Manage schema change lifecycle end-to-end: authoring, reviewing, applying, and rolling back DDL migrations against live databases without downtime or unbounded locks.
- In scope: DDL migrations, backfills, deploy sequencing for schema-dependent code.
- Out of scope (delegate): query performance → `query-optimization`; database provisioning → `iac-provisioning`; test infrastructure → `testcontainers-integration`.

## 2. Trigger Conditions
- Commands: "add a column/index/table", "schema change for X", "this migration locked the table".
- Intent patterns: any release touching schema; failed or risky deploys caused by DDL.
- Orchestration tags: `db:migrate`, `db:rollback`, `gate:schema`.

## 3. Core Directives & Standards
1. **Expand → migrate → contract.** No destructive DDL in the first release: add the new structure, backfill, switch code, then drop the old in a later release.
2. **Bounded lock times.** Single-statement DDL where possible; no long table rewrites on live tables (e.g., Postgres `ADD COLUMN ... NOT NULL DEFAULT` is phased: add nullable → backfill → set constraint); measured lock time < 1s on hot tables.
3. **Every migration ships a tested `down`.** Up then down then up must run clean in CI; untested rollbacks are not merged.
4. **Deploy ordering is explicit:** schema migrates before code that reads the new column; code is written to be dual-compatible (reads old+new) during the migration window.
5. **Backfills are batched** with progress tracking and can be paused/resumed — never one giant `UPDATE`.

## 4. Execution Workflow
1. **Intake & Analysis:** Read the current schema; identify live traffic and lock sensitivity of affected tables; check replication lag behavior for the planned DDL; list dependent code paths.
2. **Implementation:** Author up + down migrations; write the backfill (batch size, idempotent, resumable); define the deploy sequence (migrate → deploy dual-read code → contract in later release).
3. **Validation:** Run up/down/up in CI against a staging clone at production size; measure DDL lock time and replication lag; dry-run the backfill on a sample and extrapolate duration; document the rollback path.

## 5. Antipatterns & Prohibited Behaviors
- `DROP COLUMN` in the same release that adds the replacement.
- In-place type changes or implicit coercions on hot columns.
- Auto-generated migrations merged without human review.
- Down migrations that are `SELECT 1` placeholders.
- Unbatched backfills (one multi-hour `UPDATE` holding locks).

## 6. Definition of Done & Quality Guardrails
- up/down/up passes in CI (evidence attached).
- Lock time < 1s on live tables, measured on a production-sized staging replica.
- Backfill plan documented: batch size, estimated duration, pause/resume, monitoring.
- Schema documentation updated; deploy sequence (with rollback steps) recorded in the release notes.
