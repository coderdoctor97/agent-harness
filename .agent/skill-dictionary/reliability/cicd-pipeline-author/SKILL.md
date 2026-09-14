---
name: cicd-pipeline-author
description: "Author hardened CI/CD pipelines: SHA-pinned actions, least-privilege secrets, correct build caching, hashed artifacts with SBOMs, and fail-fast stage budgets."
---

# CI/CD Pipeline Author

## 1. Scope & Objective
- Design and maintain CI/CD pipelines that are fast, reproducible, and supply-chain-hardened: stages, caching, artifacts, permissions, and gates.
- In scope: pipeline design, cache strategy, artifact integrity, permission/secret hygiene, stage budgets.
- Out of scope (delegate): container image authoring → `docker-containerization`; infrastructure → `iac-provisioning`.

## 2. Trigger Conditions
- Commands: "set up CI for X", "the pipeline takes 40 minutes", "harden the pipeline", "add artifact signing".
- Intent patterns: new repo onboarding; pipeline slowdown; supply-chain incidents; release-process changes.
- Orchestration tags: `ci:author`, `ci:optimize`, `gate:pipeline`.

## 3. Core Directives & Standards
1. **Pin everything:** actions and pipeline dependencies pinned by SHA (not mutable tags); the pin list is auditable in the repo.
2. **Least-privilege credentials:** per-repo tokens, write scope only where a step proves it needs it; no shared god-tokens across environments; secrets injected per-step, never echoed or logged.
3. **Correct caching:** dependency and build caches keyed on the content hash of the lockfile/config — a cache that survives a lockfile change is a correctness bug; cache hits are measured, not assumed.
4. **Artifacts are versioned, hashed, and SBOM'd:** every published artifact carries SHA-256 and an SBOM (SPDX/CycloneDX); consumers can verify integrity.
5. **Fail fast with budgets:** ordered stages (lint → types → unit → integration → e2e) each with a time budget; total pipeline < 15 min; superseded runs are cancelled; required gates cannot use `continue-on-error`.

## 4. Execution Workflow
1. **Intake & Analysis:** Identify repo type, current pipeline pain (slowness, flakiness, security gaps), required gates, and artifact consumers; measure the current stage timings.
2. **Implementation:** Design stages with budgets; implement caching with correct keys; wire artifact publishing with hashes + SBOM; audit and shrink permissions; add concurrency/cancel rules; write the pipeline doc (stage map + budgets).
3. **Validation:** Clean run passes all gates within budget; cache invalidation proven (change lockfile → cache key changes → miss then hit); tamper test: a changed dependency is detected; secret audit of logs: 0 findings; rollback test: previous artifact re-deploys cleanly.

## 5. Antipatterns & Prohibited Behaviors
- `@latest` actions or unpinned pipeline tooling.
- One 40-minute monolithic job (no fail-fast, no signal).
- Artifacts without hashes or SBOMs ("trust the registry").
- Secrets visible in env dumps or logs (one grep finds the production key).
- Caches keyed on branch name only (stale-cache correctness incidents).
- Pipeline scripts nobody can explain (no stage map, no budgets, no owner).

## 6. Definition of Done & Quality Guardrails
- Pipeline doc delivered: stage map, budgets, owners, cache-key strategy.
- SHA-pin audit clean (0 unpinned actions/tooling).
- Cache behavior proven: hit on re-run, miss on lockfile change (evidence attached).
- Artifacts carry SHA-256 + SBOM; total pipeline under budget; secret audit of logs: 0 findings.
