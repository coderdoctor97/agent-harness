---
name: lint-formatting
description: "Configure and enforce automated linting and formatting (Biome, ESLint, Ruff) as separate style/correctness gates with zero semantic autofixes and justified-only suppressions."
---

# Lint & Formatting

## 1. Scope & Objective
- Establish and maintain static analysis and formatting for the codebase: tool selection, rule configuration, baseline cleanup, and CI/pre-commit enforcement.
- In scope: linter/formatter configuration, rule triage, baseline remediation, gate wiring.
- Out of scope (delegate): test strategy → `tdd-test-runner`; code quality review → `pr-code-reviewer`.

## 2. Trigger Conditions
- Commands: "set up linting", "formatting is inconsistent", "CI is failing on style", "which rules should we use".
- Intent patterns: new project setup; style drift between contributors; rule disputes.
- Orchestration tags: `config:lint`, `config:format`, `gate:style`.

## 3. Core Directives & Standards
1. **Formatter and linter are separate concerns:** the formatter owns style (and is always safe); the linter owns correctness rules and never rewrites semantics automatically.
2. **Semantic rules are never autofixed;** style rules may be. Anything a "fix" changes beyond formatting is a human decision.
3. **Suppressions require a reason comment plus tracking** (`eslint-disable-next-line no-undef // reason: <ticket>`); blanket disables and reasonless `# noqa` are prohibited; suppression counts are trended.
4. **Configuration is committed, versioned, and explained:** every non-default rule carries a one-line rationale; per-developer IDE overrides that diverge from CI are prohibited.
5. **Gates run everywhere:** pre-commit for speed, CI for authority (and CI checks the whole repo when config changes, not just touched files).

## 4. Execution Workflow
1. **Intake & Analysis:** Identify language/ecosystem and team conventions; count existing violations; choose the toolchain (Biome for JS/TS by default, Ruff for Python, per project norms).
2. **Implementation:** Write the config with rationales; run autofix for style; triage semantic violations (fix or justified suppression); wire pre-commit + CI; set a rule for new code (stricter than legacy where needed).
3. **Validation:** Full-repo run: 0 errors; formatter idempotency check (second run produces an empty diff); negative test — add a badly formatted file and a rule violation, confirm both gates catch it; suppression inventory exported.

## 5. Antipatterns & Prohibited Behaviors
- Disabling rules globally "to make CI green".
- Putting semantic checks in the formatter (or style checks in the linter where the formatter owns them).
- A 500-rule config nobody can explain.
- Rewriting business logic to satisfy a linter instead of fixing the underlying issue.
- Ignoring the lint debt baseline (violations grow because no one owns the count).

## 6. Definition of Done & Quality Guardrails
- 0 lint errors repo-wide (baseline remediated or explicitly frozen with an owner).
- Formatter idempotency verified (second run = empty diff).
- Pre-commit and CI gates both active; negative test (bad file) fails both.
- Every non-default rule has a documented rationale; suppression inventory exported with counts.
