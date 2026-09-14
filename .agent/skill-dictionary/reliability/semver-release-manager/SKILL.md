---
name: semver-release-manager
description: "Manage releases with strict SemVer 2.0.0: generated changelogs from Conventional Commits, deprecate-before-remove, annotated tags, and audited version bumps."
---

# SemVer Release Manager

## 1. Scope & Objective
- Cut correct, honest releases: SemVer 2.0.0 classification, changelog generation, tag hygiene, release notes, and deprecation policy for breaking changes.
- In scope: version classification, changelog, tags, release notes, deprecation tracking.
- Out of scope (delegate): pipeline mechanics → `cicd-pipeline-author`; PR review → `pr-code-reviewer`.

## 2. Trigger Conditions
- Commands: "cut a release", "what version is this change", "write the release notes", "we shipped a breaking change as minor".
- Intent patterns: release preparation; breaking changes landing; dependency version questions; changelog gaps.
- Orchestration tags: `release:cut`, `release:changelog`, `gate:release`.

## 3. Core Directives & Standards
1. **SemVer 2.0.0 is strict:** MAJOR = breaking public API change (nothing removed/changed in meaning without it); MINOR = additive, backward-compatible; PATCH = fixes. The bump is justified in the notes, not guessed.
2. **Changelogs are generated from Conventional Commits** (conventional-changelog or equivalent), then reviewed — not typed from memory at release time.
3. **Deprecate before remove:** breaking changes are announced ≥ 1 MINOR in advance (warnings in logs/docs); removal lands in the next MAJOR. Silent removal is prohibited.
4. **Tag hygiene:** annotated tags on the release commit (message = version + date + summary); the version in code must equal the tag (CI-enforced check).
5. **Release notes state the bump reason explicitly**, including a "Breaking changes" section when MAJOR (with migration guidance), and consumers run a smoke test against the new version.

## 4. Execution Workflow
1. **Intake & Analysis:** Diff since the last tag; classify each notable commit by type; identify breaking changes and verify their deprecation grace period; check version files.
2. **Implementation:** Generate the changelog (categorize: Added/Changed/Fixed/Removed/Deprecated); determine the bump with written justification; update version files; create the annotated tag; publish release notes (with breaking-change section and migration notes when MAJOR).
3. **Validation:** Changelog-vs-diff audit (no notable change missing); SemVer check (breaking present ⇒ MAJOR); tag verified (annotated, on the release commit, version matches code); downstream smoke test passes against the released artifact.

## 5. Antipatterns & Prohibited Behaviors
- "Minor" bumps for breaking changes (consumers' builds explode on auto-update).
- Changelogs that read "misc fixes" (no one can tell what changed).
- Lightweight, unannotated tags.
- Version in code diverging from the tag (two sources of truth).
- Releasing without testing the artifact; forgetting the CHANGELOG entry.

## 6. Definition of Done & Quality Guardrails
- Annotated tag on the correct commit; version files match the tag (CI check).
- Changelog complete and audited against the diff; notable changes all present.
- Bump justified in the notes; breaking changes listed explicitly with migration guidance.
- Release notes published; downstream smoke test passed (evidence attached).
