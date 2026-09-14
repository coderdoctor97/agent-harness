---
name: ast-codemods
description: "Apply AST-level source transformations (jscodeshift, ast-grep, Semgrep-fix) for symbol renames, API migrations, and deprecation upgrades with idempotency and test parity."
---

# AST Codemods

## 1. Scope & Objective
- Perform programmatic, cross-cutting source transformations: symbol renames, framework/API migrations, deprecation upgrades, pattern fixes across many files — using AST tooling, never blind regex.
- In scope: the transform itself, its test fixtures, dry-run review, and application.
- Out of scope (delegate): small one-off edits (do them directly); behavior test strategy → `tdd-test-runner`.

## 2. Trigger Conditions
- Commands: "rename X everywhere", "migrate to the new API version", "upgrade the deprecated dependency", "fix this pattern across 60 files".
- Intent patterns: a change touching 10+ files with the same mechanical shape; dependency deprecation deadlines.
- Orchestration tags: `refactor:codemod`, `migrate:api`, `refactor:rename`.

## 3. Core Directives & Standards
1. **AST, not regex.** Transforms operate on parsed syntax (jscodeshift, ast-grep, `ruff` custom rules, Semgrep `--fix`); regex is forbidden except for well-scoped string literals with an explicit note.
2. **Idempotency:** running the transform twice produces no second diff; the transform detects already-migrated code.
3. **Dry-run with reviewed diff before apply:** full diff output reviewed; the commit records the transform, its fixtures, and match counts (N files, M sites).
4. **Behavioral parity:** the relevant test suite is green before and after; the before/after failure sets are compared and any difference is explained.
5. **Edge cases get fixtures:** similar-but-different identifiers, string mentions, comments, dynamic dispatch — each has a test case for the transform.

## 4. Execution Workflow
1. **Intake & Analysis:** Define the pattern precisely; collect all match sites (counts per file); enumerate edge cases (near-miss names, strings, dynamic usages).
2. **Implementation:** Write the transform; write its fixture tests (input → expected output per case, including no-op cases); dry-run; review the full diff; apply; run the suite.
3. **Validation:** Zero remaining old-pattern matches (verified by search); second run of the transform is a no-op (empty diff); suite parity confirmed (same failures as before, none new, intended fixes applied); commit includes transform + fixtures + counts.

## 5. Antipatterns & Prohibited Behaviors
- Regex `replace` across the codebase for a "simple rename".
- Transforms that change semantics beyond the stated migration (scope creep inside a codemod).
- Skipping edge-case fixtures ("it's just a rename").
- Bundling five unrelated changes into one codemod (unreviewable diff).
- No before/after test comparison (behavior drift hidden inside the "mechanical" change).

## 6. Definition of Done & Quality Guardrails
- 0 residual old-pattern matches (search evidence attached).
- Second transform run is a no-op (idempotency evidence).
- Test suite parity: no new failures vs. the pre-change baseline.
- Commit contains the transform, its fixture tests, and the file/site counts.
