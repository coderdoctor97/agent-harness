---
name: secret-credential-scanner
description: "Prevent and remediate credential leaks: high-entropy and known-prefix scanning in pre-commit, CI, and history, with rotate-first incident handling."
---

# Secret & Credential Scanner

## 1. Scope & Objective
- Stop credentials from entering (or remaining in) the codebase: continuous scanning (new and historical), pattern + entropy detection, and rotate-first incident handling for any finding.
- In scope: scanner configuration and gates, triage, remediation, prevention habits (`.env.example`, log hygiene).
- Out of scope (delegate): dependency CVEs → `security-cve-audit`; IAM/session design → `auth-security`.

## 2. Trigger Conditions
- Commands: "scan for leaked keys", "did we ever commit a secret", "add secret scanning", "someone pasted a token into a PR".
- Intent patterns: any new file containing key-shaped content; pre-commit/CI wiring; suspected leak incidents; test fixture reviews.
- Orchestration tags: `sec:secrets`, `gate:secrets`.

## 3. Core Directives & Standards
1. **Rotate first, then remove.** A real finding is an incident: rotate the credential immediately, then scrub history (`git filter-repo`/BFG) — deleting the line without rotating is not remediation.
2. **Three scan layers:** pre-commit (fast, local), CI (blocking, on every PR), and on-demand historical scan (full history); known provider prefixes (AKIA…, ghp_, xoxb-, sk-, AIza…) plus high-entropy fallback.
3. **No secrets in any output surface:** logs, error messages, env dumps, test fixtures, or CI output — tests use obviously-fake values matching documented test patterns.
4. **`.env.example` documents names and shapes, never values;** the real `.env` is git-ignored and its absence fails fast via `env-config-validator`, not silently.
5. **Findings are triaged, not just counted:** real / false-positive / stale — each with a verdict and (for real) a rotation ticket; FP suppressions are reviewed, never bulk-ignored.

## 4. Execution Workflow
1. **Intake & Analysis:** Run current + historical scans; classify findings (real / FP / stale); assess exposure window for real findings (when was the secret live? what could it touch?).
2. **Implementation:** For real findings: rotate (ticket + owner), scrub history, add the pattern to the blocklist, and wire the missing gate; for the repo: pre-commit + CI hooks, `.env.example` in place, log-surface audit.
3. **Validation:** Rescan: 0 unaddressed real findings (or documented FPs with justification); gate negative test — a test secret committed is blocked by pre-commit and CI; rotation verified (old credential rejected, new one works).

## 5. Antipatterns & Prohibited Behaviors
- Delete-without-rotate (the "leaked" credential keeps working).
- Bulk-ignoring FPs until the scanner is noise (gate disabled by fatigue).
- "It's a test key" sitting in production configuration.
- Secrets in log lines ("auth failed, token=sk-…").
- Scanning only new commits while history holds years of leaks.

## 6. Definition of Done & Quality Guardrails
- 0 unaddressed real findings; every real finding has verified rotation (old key rejected).
- Pre-commit + CI gates active and negative-tested (planted secret is blocked).
- Historical scan completed with a report; FP suppressions individually justified.
- `.env.example` pattern in use; log-surface audit shows 0 secret values.
