---
name: license-compliance-audit
description: "Audit transitive dependency licenses for copyleft exposure: full-tree classification, legal gates for strong copyleft, and per-release SBOM generation."
---

# License Compliance Audit

## 1. Scope & Objective
- Know what license every dependency — including transitive ones — carries, and keep the product legally compliant: classification, copyleft handling, SBOM generation, and attribution.
- In scope: license scanning, classification, copyleft gates, SBOM, NOTICE/attributions.
- Out of scope (delegate): vulnerability scanning → `security-cve-audit`; code originality/legal advice (route to counsel).

## 2. Trigger Conditions
- Commands: "what licenses are we using", "is GPL a problem here", "new dependency review", "generate the SBOM".
- Intent patterns: new dependencies; release gates; vendor/compliance audits; OSS usage questions.
- Orchestration tags: `sec:license`, `compliance:audit`, `gate:licenses`.

## 3. Core Directives & Standards
1. **Full transitive scan, always:** direct dependencies are a minority of the truth; the audit covers the complete tree (license-report, osb, syft, or equivalent).
2. **Classification is explicit per dependency:** permissive (MIT/Apache/BSD) / weak copyleft (LGPL/MPL) / strong copyleft (GPL/AGPL) / unusual (SSPL, BSL, "source-available", "custom") — anything unusual goes to legal review before merge.
3. **Strong copyleft in a distributed product is a legal gate:** no silent inclusion; the options are replace, isolate (separate process/service boundary), or documented legal waiver.
4. **An SBOM (SPDX or CycloneDX) is generated per release** and published with it; the dependency tree in the SBOM matches the actual lockfile.
5. **Attribution obligations are met:** NOTICE/attributions file complete (copyright notices per MIT-style requirements, license texts where required); headers are never deleted.

## 4. Execution Workflow
1. **Intake & Analysis:** Generate the full dependency tree with licenses; classify every entry; flag strong copyleft and unusual licenses; check for dual-licensed components (is the picked variant the right one?).
2. **Implementation:** Resolve flagged items: replace (prefer permissively-licensed equivalents), isolate (process/service boundary for AGPL-class), or waive (legal sign-off, recorded with expiry); update NOTICE/attributions; generate the SBOM.
3. **Validation:** Rescan: classification report current, 0 unknown licenses; 0 strong copyleft without a documented legal waiver; SBOM matches the lockfile (diff check); NOTICE file complete against the license requirements; CI gate blocks new strong-copyleft without the waiver flag.

## 5. Antipatterns & Prohibited Behaviors
- Trusting direct-dependency licenses only (transitive GPL/AGPL is how companies find out).
- "It's free, so it's fine" (license ≠ price; free software has conditions).
- Deleting license headers or NOTICE files "to clean up".
- Dual-licensed components where the wrong variant was picked (the proprietary variant was the only option).
- No SBOM: when audited, the company cannot answer "what's in it" within the deadline.

## 6. Definition of Done & Quality Guardrails
- License report current: 100% of dependencies classified, 0 unknown/unclassified.
- 0 strong-copyleft components without a documented legal waiver (recorded, with owner + expiry).
- SBOM (SPDX or CycloneDX) attached to the release and verified against the lockfile.
- NOTICE/attributions file complete; CI gate active for new strong-copyleft additions.
