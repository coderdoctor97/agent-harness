---
name: env-config-validator
description: "Validate 12-factor environment configuration at boot: strict typed schemas, fail-fast missing-variable errors, complete .env.example, and redacted logging."
---

# Env & Config Validator

## 1. Scope & Objective
- Make configuration a typed, validated, first-class contract: 12-factor env configuration, strict boot-time validation, complete `.env.example`, and secret-safe logging.
- In scope: config schemas, boot validation, defaults policy, environment precedence, log redaction.
- Out of scope (delegate): secret storage infrastructure → `iac-provisioning`; per-service config content policy.

## 2. Trigger Conditions
- Commands: "it works locally but not in prod", "missing env var crashed the service", "add configuration for X", "centralize the config".
- Intent patterns: new service onboarding; config-related incidents; scattered `process.env` reads; missing-variable crashes.
- Orchestration tags: `config:validate`, `config:env`, `gate:config`.

## 3. Core Directives & Standards
1. **12-factor: config comes from the environment** — zero environment-specific values hardcoded in code; the schema is the single source of truth for what the service needs.
2. **Validate at boot, fail fast:** a strict typed schema (zod / envy / pydantic-settings) checks every variable on startup; a missing or mistyped variable produces a typed error naming the variable, its expected type, and a documentation pointer — never an `undefined` two hundred milliseconds into runtime.
3. **Required variables have no silent defaults:** `VAR || "production"`-style fallbacks for required config are prohibited; defaults exist only for genuinely optional settings and are documented.
4. **Precedence is explicit and documented:** env > config file > defaults, with the rule stated in the README and covered by a test.
5. **Secrets are name-visible, value-invisible:** error messages and logs may name a missing secret variable, never its value; log redaction is enforced and audited.

## 4. Execution Workflow
1. **Intake & Analysis:** Inventory every config variable (where used, per-environment differences, which are secrets); list current failure modes (silent defaults, scattered reads, crashes deep in runtime).
2. **Implementation:** Write the typed schema (required/optional + constraints + parse rules for int/bool/duration); wire boot-time validation with helpful errors; publish a complete `.env.example` (names, types, example shapes — never real values); remove silent defaults from required vars; add redaction to the logging layer.
3. **Validation:** Boot tests: each required variable missing → clean named error (one test per variable); wrong type → clean error; precedence test (env beats file beats default); prod config surface diffed against `.env.example` (parity = 0); log audit: 0 secret values in any output.

## 5. Antipatterns & Prohibited Behaviors
- `process.env.X || "production"` for required configuration (silent wrong-env behavior).
- Secrets in log lines or error messages (the value, not just the name).
- Configuration scattered across a dozen files with no single schema.
- Committing real `.env` files (git-ignored but pasted into issues).
- Per-request `if (env === "prod")` in business logic (the environment is a boot-time fact, not a runtime branch).

## 6. Definition of Done & Quality Guardrails
- Single typed schema exists and is the source of truth (all reads go through it).
- Boot validation with per-variable missing/type tests (green suite).
- `.env.example` complete: diff against the schema surface = 0 variables missing.
- Precedence documented and tested; log audit shows 0 secret values; real `.env` git-ignored.
