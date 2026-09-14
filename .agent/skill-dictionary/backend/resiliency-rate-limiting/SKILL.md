---
name: resiliency-rate-limiting
description: "Implement resiliency patterns: edge rate limiting with 429 semantics, per-dependency timeouts, bounded retries, and circuit breakers with fallbacks."
---

# Resiliency & Rate Limiting

## 1. Scope & Objective
- Harden services against dependency failure and abuse: rate limiting at the edge, timeouts, bounded retries, circuit breakers, bulkheads, and explicit degradation paths.
- In scope: client-side and server-side resiliency patterns for all outbound and inbound traffic.
- Out of scope (delegate): load/stress validation of the patterns → `load-stress-testing`; async job retries → `queue-workers`.

## 2. Trigger Conditions
- Commands: "X is flaky and taking down Y", "add rate limiting to the API", "retries are making it worse", "we need a circuit breaker on Z".
- Intent patterns: cascading failures; new outbound dependencies; abuse or abuse-suspected endpoints.
- Orchestration tags: `resilience:implement`, `ratelimit:config`, `gate:resilience`.

## 3. Core Directives & Standards
1. **Every outbound call has explicit timeouts** (connect < read; total budget ≤ the caller's SLA budget) — no default-infinite sockets.
2. **Retries are bounded and honest:** only for idempotent or verified-retriable operations; exponential backoff + jitter; global retry budget (retries ≤ ~10% of total traffic) so retries can't amplify overload.
3. **Circuit breakers per dependency** with open/half-open/closed states, configured thresholds, and a defined fallback/degradation response per state.
4. **Rate limiting at the edge** (per user/IP/API key) using sliding window or token bucket; responses use 429 with a correct `Retry-After`.
5. **Every dependency has a documented degradation path:** what the user gets when the dependency is down (cached value, reduced feature, queued request) — "it fails open/closed" is a documented decision, not an accident.

## 4. Execution Workflow
1. **Intake & Analysis:** Map dependencies: upstream callers, downstream deps, SLA per hop, current failure modes; pick the limiter algorithm and key strategy.
2. **Implementation:** Timeouts + per-dependency retry policies; circuit breakers with state observability; edge limiter with 429 + `Retry-After`; fallback paths wired and tested.
3. **Validation:** Chaos pass — kill a downstream dependency: breaker opens, fallback serves, half-open recovery observed; rate-limit test → correct 429 + `Retry-After`; retry budget verified in metrics during a simulated failure storm.

## 5. Antipatterns & Prohibited Behaviors
- Retries without timeouts (worsens overload instead of recovering from it).
- Circuit breakers that never half-open (permanently dark dependencies).
- "Retry on 500" applied to non-idempotent POSTs.
- Limiters that return 500 instead of 429 + `Retry-After`.
- Unlimited retry counts or retry budgets that are unmeasured.

## 6. Definition of Done & Quality Guardrails
- Every outbound dependency has documented timeout, retry, and breaker configuration.
- Chaos test demonstrates isolation: one dependency's failure does not degrade unrelated routes (evidence attached).
- 429 path tested: correct status, correct `Retry-After`, no 500s from the limiter.
- Retry budget enforced and visible in metrics during the failure-storm test.
