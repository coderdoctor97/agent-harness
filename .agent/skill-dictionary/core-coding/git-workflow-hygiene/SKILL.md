---
name: git-workflow-hygiene
description: "Enforce VCS discipline: atomic Conventional Commits, clean rebased branches, no secrets or junk in history, and reviewable diff sizes."
---

# Git Workflow Hygiene

## 1. Scope & Objective
- Keep version-control output reviewable and safe: atomic conventional commits, clean branch histories, and zero accidental artifacts (secrets, binaries, WIP junk) in history.
- In scope: staging strategy, commit messages, rebasing, branch hygiene, pre-push checks.
- Out of scope (delegate): PR content review → `pr-code-reviewer`; release/tagging → `semver-release-manager`.

## 2. Trigger Conditions
- Commands: "prepare this PR", "clean up this branch", "the commit history is a mess", "set up commit conventions".
- Intent patterns: any commit; PR preparation; merge-conflict resolution; force-push decisions.
- Orchestration tags: `git:commit`, `git:rebase`, `gate:history`.

## 3. Core Directives & Standards
1. **Atomic commits:** one concern per commit, each self-contained and buildable; a reviewer should be able to cherry-pick any commit and have it make sense.
2. **Conventional Commits taxonomy** (`feat|fix|refactor|docs|test|chore|perf|ci` + optional scope); the type reflects the change, and the summary fits on one line.
3. **Rebase feature branches onto main before review** (clean, linear history); merge commits reserved for main-bound merges; **no force-push to protected or shared branches, ever.**
4. **Reviewable sizes:** commits and PR diffs stay small (target < ~400 lines per commit; split larger changes); no "everything" commits.
5. **Nothing accidental in history:** no secrets, no `.env`, no build artifacts, no WIP markers; pre-commit hooks + secret scan run on every commit.

## 4. Execution Workflow
1. **Intake & Analysis:** Inspect the working tree and dirty state; group changes by concern (feature / fix / docs / config); check for accidental files (`.gitignore` audit).
2. **Implementation:** Stage concern-by-concern; write conventional messages (imperative summary, rationale in body where non-obvious); verify each commit builds; rebase onto main; resolve conflicts by re-deriving intent, not taking "theirs" wholesale.
3. **Validation:** `git log --oneline` tells the change's story in order; `git diff main` matches the PR description; per-commit build/test check passed; secret scan clean on the new commits; no binary or junk files staged.

## 5. Antipatterns & Prohibited Behaviors
- "work in progress" / "asdf" / "fix" commits.
- Mixed concern commits (refactor + feature + docs in one).
- `git commit --amend` on a pushed shared commit (rewrites others' history).
- Merge-commit spam on feature branches instead of rebasing.
- Force-pushing a shared branch "to clean up" history.

## 6. Definition of Done & Quality Guardrails
- Every commit is atomic, conventional, and passes its build/test check (evidence: per-commit run log).
- Branch history is linear from main; PR diff matches the description.
- Secret scan: 0 findings in new commits; `.gitignore` covers all known artifact classes.
- Hooks active (pre-commit lint/format/secret scan) and verified with a negative test.
