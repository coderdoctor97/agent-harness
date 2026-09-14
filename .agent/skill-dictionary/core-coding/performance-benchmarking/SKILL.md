---
name: performance-benchmarking
description: "Measure and optimize performance with fixed-methodology benchmarks, profiler-driven optimization, and statistically sound before/after comparisons."
---

# Performance Benchmarking

## 1. Scope & Objective
- Find and eliminate performance problems with evidence: profiling to locate hot spots, fixed-methodology benchmarks, algorithmic improvements, and regression guards.
- In scope: CPU/memory profiling, micro- and macro-benchmarks, optimization with measured proof.
- Out of scope (delegate): database query plans → `query-optimization`; system load under traffic → `load-stress-testing`.

## 2. Trigger Conditions
- Commands: "it's slow", "optimize this function", "perf regression alert", "why did latency jump".
- Intent patterns: any optimization PR (must include measurements); new hot paths; memory-growth reports.
- Orchestration tags: `perf:profile`, `perf:bench`, `gate:perf`.

## 3. Core Directives & Standards
1. **Profile before optimizing.** No optimization without a flame graph or profiler output pointing at the hot path; "this looks slow" is not evidence.
2. **Fixed methodology:** warmup iterations, sufficient sample count, report median + p95 (never the mean alone), same machine/conditions for before and after; the method is written down in the PR.
3. **Right tool per question:** micro-benchmarks (hyperfine, `benchmark` modules, JMH) for functions; profilers (perf, py-spy, CPU sampler, flame graphs) for systems; heap snapshots for memory.
4. **Every optimization ships before/after numbers** on the same harness with the same data; data-dependent code gets a complexity note (n → n log n).
5. **No regressions hidden in optimizations:** memory checked (heap diff / leak check), and critical paths get a committed perf guard in CI.

## 4. Execution Workflow
1. **Intake & Analysis:** State the target (SLO or improvement goal); profile to find the actual hot path; build the harness (realistic data fixture + representative workload).
2. **Implementation:** Capture the baseline (≥ 3 runs, variance low); apply the change; re-measure on the identical harness; iterate while the target is missed and the profiler still justifies further work.
3. **Validation:** p95 meets the target (or the evidence explains why not); no new memory growth (heap snapshot diff clean); the harness is committed and repeatable; results table (baseline vs after, median + p95) attached to the PR.

## 5. Antipatterns & Prohibited Behaviors
- "It feels faster" (no measurement).
- Micro-benchmarks on unrealistic data (1-element arrays, empty inputs).
- Single-run benchmarks (noise passed as signal).
- Premature optimization with no SLO or profile backing it.
- Micro-optimizing readability away without a measurement that demanded it.

## 6. Definition of Done & Quality Guardrails
- Baseline and after-measurements with documented methodology (≥ 3 runs, median + p95).
- Target met, or the gap is explained with evidence.
- Memory check clean (no leak introduced by the optimization).
- Harness committed and repeatable; critical path has a perf guard in CI (where applicable).
