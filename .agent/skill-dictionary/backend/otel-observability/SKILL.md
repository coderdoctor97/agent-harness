---
name: otel-observability
description: "Instrument services with OpenTelemetry: W3C trace propagation, RED metrics, structured JSON logs with trace correlation, and bounded cardinality."
---

# OpenTelemetry Observability

## 1. Scope & Objective
- Instrument services for production observability: distributed tracing, metrics, and structured logging correlated by trace/span IDs — with cardinality and PII discipline.
- In scope: SDK setup, spans, metrics, log correlation, sampling, propagation.
- Out of scope (delegate): dashboard and alert infrastructure → `iac-provisioning`; load behavior → `load-stress-testing`.

## 2. Trigger Conditions
- Commands: "add tracing to X", "I can't follow a request across services", "the logs have no correlation ID".
- Intent patterns: new service onboarding; debugging a cross-service failure with no context; metrics gaps.
- Orchestration tags: `obs:tracing`, `obs:metrics`, `gate:observability`.

## 3. Core Directives & Standards
1. **Propagation is total:** W3C TraceContext on every outbound call (HTTP headers, message headers); a primary request must produce one continuous trace across all services.
2. **Structured JSON logs only;** every log line carries `trace_id` + `span_id`; jump from any log line to its trace must work.
3. **RED metrics per operation:** rate, errors, duration histograms per service and per operation (not one "the service" metric).
4. **Cardinality budget:** no user IDs, emails, or request-specific values in metric labels or span attributes that fan out; attribute allowlist enforced.
5. **PII redaction:** span attributes and log fields scrubbed (emails, names, tokens); redaction tested, not assumed.

## 4. Execution Workflow
1. **Intake & Analysis:** Map the request path across services; identify uninstrumented hops; list current log formats and metric gaps; define the sampling strategy (head-based for high RPS, 100% for errors).
2. **Implementation:** SDK + auto-instrumentation for frameworks and libraries; manual spans at business boundaries (not per SQL row); wire log correlation; publish RED metrics; enforce the attribute allowlist and PII redaction.
3. **Validation:** Follow one real request: the trace is continuous across every service in the UI; log-to-trace jump works from a random log line; metric cardinality audited (label value counts within budget); PII scan of span/log samples clean.

## 5. Antipatterns & Prohibited Behaviors
- A span per SQL row or per loop iteration (trace noise swallows signal).
- Logs without correlation IDs (every incident starts with "which logs…?").
- User PII in span attributes or metric labels.
- 100% sampling of everything on a high-RPS service.
- Errors logged with no span event (traces dead-end exactly where incidents live).

## 6. Definition of Done & Quality Guardrails
- End-to-end trace complete for every primary flow (demonstrated in the trace UI).
- Log-to-trace navigation works from any sampled line (verified, not assumed).
- Cardinality within budget (top label value counts reported).
- PII scan of span attributes and log samples: 0 findings; redaction rule tests green.
