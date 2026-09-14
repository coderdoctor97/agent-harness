---
name: query-optimization
description: "Diagnose and fix slow data access: EXPLAIN-driven index planning, N+1 elimination, and cursor pagination with measured before/after."
---

# Query Optimization

## 1. Scope & Objective
- Find and fix the slowest data access paths: query plans, index strategy, N+1 patterns, pagination — with measurement, not guesswork.
- In scope: query rewriting, index design, ORM access patterns, pagination.
- Out of scope (delegate): schema change mechanics → `db-migrations`; caching infrastructure; load testing → `load-stress-testing`.

## 2. Trigger Conditions
- Commands: "this endpoint is slow", "DB CPU is spiking", "the page takes 3 seconds", "optimize this query".
- Intent patterns: latency alerts, expensive-query reports, user-reported slowness.
- Orchestration tags: `db:perf`, `perf:queries`.

## 3. Core Directives & Standards
1. **EXPLAIN before indexing.** No index work without `EXPLAIN (ANALYZE, BUFFERS)` evidence; every proposed index cites the plan it fixes.
2. **Index design rules:** composite order = equality columns first, then range columns; prefer covering indexes on hot read paths; audit for duplicate/unused indexes after every change.
3. **N+1 is eliminated at the source** (batch queries, data loaders, explicit eager loading) — never hidden under a caching layer.
4. **Cursor-based (keyset) pagination** for any list longer than a few pages; deep `LIMIT/OFFSET` is prohibited.
5. **Measure before and after** on the same dataset: p95 latency per query/endpoint, and query count per request where N+1 was fixed.

## 4. Execution Workflow
1. **Intake & Analysis:** Pull the top queries by *total* time (not count); capture current EXPLAIN plans; map each slow query to its endpoint and ORM call site.
2. **Implementation:** Rewrite queries as needed; add/merge/prune indexes with justification; fix access patterns (batching, eager loads); replace OFFSET pagination with keyset.
3. **Validation:** Before/after EXPLAIN attached; p95 latency measured on staging for the affected endpoints; per-request query count verified for N+1 fixes; index audit shows no new unused or duplicate indexes.

## 5. Antipatterns & Prohibited Behaviors
- "Just in case" indexes (no plan evidence).
- `SELECT *` in hot paths.
- Deep `LIMIT 10 OFFSET 100000` pagination.
- Hiding N+1 behind a cache instead of fixing the access pattern.
- Denormalizing or adding a second database before measuring.

## 6. Definition of Done & Quality Guardrails
- Target endpoints meet their p95 SLA, with before/after measurements attached.
- 0 new unused or duplicate indexes (index audit clean).
- N+1 patterns removed, verified by per-request query count.
- Every added index has its EXPLAIN rationale in the PR; every removed/kept index audited.
