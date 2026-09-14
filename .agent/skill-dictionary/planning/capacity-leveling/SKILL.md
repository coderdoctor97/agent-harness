---
name: capacity-leveling
description: "Level capacity against demand: honest allocation (≤100%), WIP limits, range-based estimates, bottleneck mitigation, and capacity-driven commitments."
---

# Capacity Leveling

## 1. Scope & Objective
- Match people and time to work honestly: capacity computation, WIP limits, estimation ranges, bottleneck mitigation, and commitments that follow capacity rather than deadlines.
- In scope: planning math, workload balancing, overload prevention, throughput reality-checks.
- Out of scope (delegate): dependency/float math → `critical-path-mapping`; task decomposition → `wbs-decomposition`.

## 2. Trigger Conditions
- Commands: "what can we commit for this sprint/release", "everyone is overloaded", "throughput keeps missing plan", "balance the team load".
- Intent patterns: planning/commitment sessions; overload signals; uneven load; repeated late deliveries.
- Orchestration tags: `plan:capacity`, `plan:leveling`.

## 3. Core Directives & Standards
1. **Capacity is people × time × focus factor (≤ 0.8)** — meetings, interruptions, and variance eat the rest; committing at 100% allocation is prohibited ("heroics" is a failure mode, not a mode).
2. **WIP limits are set per person/stage** (in-flight ≤ 2 by default); unlimited WIP is a throughput tax paid by everyone.
3. **Estimates are ranges with confidence** (e.g., "2–4 days, 70% confident"), never single-point numbers; commitments use the range, not the optimistic end.
4. **No one exceeds 110% allocation; no single-owner task sits on the critical path** without a named backup or reduced load.
5. **Commitments are pulled by capacity, pushed by no deadline:** the plan is `demand vs capacity` with an explicit gap-closing decision (descope / extend date / add capacity).

## 4. Execution Workflow
1. **Intake & Analysis:** Inventory: people, skills, availability, current WIP, incoming demand (from the WBS with estimates); compute capacity per person per period with the focus factor.
2. **Implementation:** Gap analysis (demand vs capacity); level — reorder, descope, or extend dates with a recorded decision; set WIP limits; flag single-owner critical tasks and assign backups; record the commitment math.
3. **Validation:** Re-verify the plan: 0 allocations above 100% (table attached); WIP limits set per stage; every single-point ownership flagged with mitigation; the commitment is traceable to the capacity calculation (no unexplained slack or stretch).

## 5. Antipatterns & Prohibited Behaviors
- 100% allocation to everyone ("we'll crush it").
- Unlimited WIP (context-switch tax hiding in "busyness").
- Reverse-engineering estimates from deadlines (the number comes from the date, not the work).
- Single-point ownership on the critical path with no backup ("she's the only one who knows").
- Committing by deadline and hoping the capacity math is wrong.

## 6. Definition of Done & Quality Guardrails
- Capacity table delivered: person × period × allocation, all ≤ 100% (evidence attached).
- WIP limits set per person/stage and communicated.
- Demand/capacity gap closed by a recorded decision (descope / extend / add capacity).
- Single-point ownership on the critical path: 0 unmitigated instances.
