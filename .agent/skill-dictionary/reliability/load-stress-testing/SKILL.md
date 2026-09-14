---
name: load-stress-testing
description: "Run scripted k6/Locust load, spike, and soak tests against explicit p99/error-rate SLAs, with baselines and saturation-point identification."
---

# Load & Stress Testing

## 1. Scope & Objective
- Prove the system holds under load: scripted load/stress/spike/soak tests (k6/Locust) against explicit per-endpoint SLAs, with baseline regression tracking and saturation-point discovery.
- In scope: test scripts, load profiles, SLA thresholds, saturation/spike/soak runs, baseline comparison.
- Out of scope (delegate): input-robustness fuzzing → `api-fuzz-tester`; function-level perf → `performance-benchmarking`.

## 2. Trigger Conditions
- Commands: "will it hold 10× traffic", "run a load test", "define the SLAs", "spike test the payment flow".
- Intent patterns: pre-scale decisions; new infrastructure; SLA definition; releases with capacity-relevant changes.
- Orchestration tags: `load:run`, `load:spike`, `gate:capacity`.

## 3. Core Directives & Standards
1. **Explicit SLAs per endpoint:** p99 latency + error rate at a stated load (e.g., "p99 < 300 ms @ 1k RPS, errors < 0.1%") — "didn't crash" is not a pass criterion.
2. **Realistic profiles:** realistic data shapes, read/write mixes, and think times — hammering one endpoint with tiny payloads proves nothing about production.
3. **Four test shapes:** ramp (find saturation), constant load (verify SLA), spike (sudden 10× for 1 min — does it recover?), soak (2–4 h at ~70% — memory flat?).
4. **Baselines are mandatory:** every run compares against the last run at the same load; a p99 regression > 10% at equal load fails the release.
5. **Environment honesty:** the test environment's capacity relative to production is stated; a 1/100th-scale environment produces scaled findings, not absolutes.

## 4. Execution Workflow
1. **Intake & Analysis:** Gather SLO/SLAs, endpoint mix, data volumes, and environment capacity vs production; define the load profile (phases, rates, data).
2. **Implementation:** Author k6/Locust scenarios (ramp-up, constant, spike, soak) with threshold assertions per SLA; seed realistic data; wire artifact output (graphs + JSON).
3. **Validation:** Run the battery; thresholds green/red per SLA recorded; saturation point identified (RPS where p99 degrades); baseline diff produced (regression ≤ 10% p95 at equal load); soak run shows flat memory; failures become tickets with evidence.

## 5. Antipatterns & Prohibited Behaviors
- Single-endpoint hammering presented as "the load test".
- "It didn't crash" declared as the result.
- No baseline (regressions are invisible by definition).
- Synthetic data too easy for the system (small rows, zero contention).
- 1/100th-scale environments concluding "no problem at all" without the scale factor stated.
- Looking at latency while ignoring error rate (the 0.5% 500s are the incident).

## 6. Definition of Done & Quality Guardrails
- Scripts committed and runnable; scenario set covers ramp, spike, and soak.
- SLA table per endpoint with pass/fail per run (evidence attached).
- Saturation point documented (RPS + observed degradation behavior).
- Baseline comparison: p95 regression ≤ 10% at equal load; 2 h soak clean (memory flat).
- Report with graphs and JSON artifacts attached to the ticket/release.
