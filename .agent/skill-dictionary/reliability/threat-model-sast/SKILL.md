---
name: threat-model-sast
description: "Run proactive security assessments: STRIDE per trust boundary, OWASP Top 10 mapping, severity scoring, and a SAST baseline that gates PRs."
---

# Threat Model & SAST

## 1. Scope & Objective
- Assess and document system security before incidents: data-flow mapping, STRIDE analysis per trust boundary, OWASP mapping, severity scoring, and a standing SAST gate.
- In scope: threat modeling, SAST tooling and triage, mitigation tracking.
- Out of scope (delegate): dependency CVEs → `security-cve-audit`; leaked credentials → `secret-credential-scanner`; implementing individual controls.

## 2. Trigger Conditions
- Commands: "threat model X", "security review before launch", "what can be attacked here", "set up SAST".
- Intent patterns: new systems/features touching data; architecture changes crossing trust boundaries; post-incident hardening.
- Orchestration tags: `sec:threat`, `sec:sast`, `gate:security`.

## 3. Core Directives & Standards
1. **Map data flows and trust boundaries first;** STRIDE (Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege) is applied per boundary — a checklist without a system map is theater.
2. **Every threat maps to OWASP Top 10 (2021+)** and carries a severity (CVSS or DREAD) with a written rationale — unexplained severities are not accepted.
3. **Every high-severity threat has a mitigation, an owner, and a verification** (a test or check that proves the mitigation works) — or a documented, dated risk acceptance.
4. **SAST is standing, not episodic:** Semgrep/CodeQL (or equivalent) baseline ruleset; 0 *new* high findings in a PR is a merge gate; triage verdicts are recorded, not silently ignored.
5. **The model is versioned and re-run on change:** triggers for re-analysis are written (new boundary, new data class, new integration).

## 4. Execution Workflow
1. **Intake & Analysis:** Build/refresh the data-flow diagram; identify assets (crown jewels), trust boundaries, and external inputs; run the SAST baseline and collect findings.
2. **Implementation:** STRIDE table per boundary; OWASP mapping; severity scoring with rationales; mitigations (including existing controls) with owners and verification; wire the SAST gate into CI.
3. **Validation:** Independent review of the threat table (a second reader challenges it); 100% of highs have mitigation + verification or a dated acceptance; SAST gate proven with a negative test (planted vulnerable code fails the PR); re-analysis triggers documented.

## 5. Antipatterns & Prohibited Behaviors
- Copying the OWASP checklist without system-specific analysis (the threat model that applies to every company equally proves nothing).
- Skipping the data-flow step (you can't attack what you haven't mapped).
- Severity scores without rationale (all "8" or all "3").
- Mitigations without verification ("we fixed it" is not evidence).
- A model written once, never revisited, and quietly obsolete.

## 6. Definition of Done & Quality Guardrails
- Threat table delivered: boundary × STRIDE × OWASP × severity × mitigation × status, reviewed by a second reader.
- 100% of high-severity threats have mitigation + verification, or a documented dated risk acceptance.
- SAST baseline + CI gate active (negative test evidence attached).
- Model versioned with explicit re-analysis triggers.
