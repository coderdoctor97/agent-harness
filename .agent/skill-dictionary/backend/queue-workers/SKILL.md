---
name: queue-workers
description: "Build and operate idempotent background job systems with bounded retries, exponential backoff with jitter, and monitored dead-letter queues."
---

# Queue Workers & Background Jobs

## 1. Scope & Objective
- Design and harden background job processing: idempotency, delivery semantics, retry policy, dead-letter handling, and job observability.
- In scope: job definitions, workers, retry/DLQ policies, deduplication, job metrics.
- Out of scope (delegate): broker infrastructure and scaling → `iac-provisioning`; load behavior → `load-stress-testing`.

## 2. Trigger Conditions
- Commands: "run X in the background", "jobs are piling up", "the DLQ has items", "retries are hammering the DB".
- Intent patterns: any feature needing async work; stuck/failed job alerts; retry storms.
- Orchestration tags: `jobs:implement`, `jobs:reliability`, `gate:jobs`.

## 3. Core Directives & Standards
1. **Every job is idempotent:** dedup key at the enqueue boundary *and* idempotent effects (upserts, conditional writes) — delivery is at-least-once, so double delivery is a given, not an edge case.
2. **Bounded retries with backoff + jitter** (e.g., max 5, base 1s ×2 with jitter); after the cap the job goes to a DLQ — infinite retries are prohibited.
3. **DLQ is observable and actionable:** alert on depth, replay tooling tested, and poison messages (schema-invalid payloads) route to DLQ immediately without consuming retry budget.
4. **Timeouts and visibility:** job timeout < visibility timeout; long work is checkpointed, not held in one blocking call.
5. **Record before effect:** the durable record (job claimed, attempt N) is written before side effects execute, so crashes are recoverable without duplicate effects.

## 4. Execution Workflow
1. **Intake & Analysis:** Inventory jobs: volume, side effects, retryability, cost of duplicate execution, current failure modes; define per-job retry policy (not one global policy for all).
2. **Implementation:** Idempotency layer (dedup table/keys + idempotent writes); per-job retry policies with backoff + jitter; DLQ wiring with alerts and replay; metrics (attempts, age, DLQ depth, error rate per job type).
3. **Validation:** Kill-the-worker-mid-job test → no duplicate effects; retry storm test → backoff observed in metrics; DLQ replay test → replayed jobs succeed idempotently; p95 job age within SLA.

## 5. Antipatterns & Prohibited Behaviors
- Retries without backoff (thundering herd on a recovering dependency).
- Side effects before the durable record (crash = silent lost work).
- Jobs that block longer than their visibility timeout.
- Silent DLQs (no alert, no replay path, no ownership).
- One shared worker pool for millisecond jobs and minute-long jobs.

## 6. Definition of Done & Quality Guardrails
- Double-delivery test passes: effect executes exactly once (evidence: test + metrics).
- Per-job retry policy documented (max attempts, backoff, jitter, DLQ behavior).
- DLQ alert fires in staging; replay tested end-to-end.
- Job metrics dashboard live: attempts, age, DLQ depth, error rate per job type.
