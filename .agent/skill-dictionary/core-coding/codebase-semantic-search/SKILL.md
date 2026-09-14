---
name: codebase-semantic-search
description: "Map code understanding via symbol search, call graphs, and dependency mapping to produce impact reports before refactors and cross-module changes."
---

# Codebase Semantic Search

## 1. Scope & Objective
- Build verified understanding of a codebase before acting: symbol lookup, call-site mapping, cross-module dependency graphs, test coverage of a path — producing an impact report an agent can act on.
- In scope: search strategy, impact analysis, flow tracing, dynamic-dispatch detection.
- Out of scope (delegate): making the change (the owning skill); design decisions (planning/architecture skills).

## 2. Trigger Conditions
- Commands: "where is X used", "what depends on Y", "how does the flow work", "what breaks if I change Z".
- Intent patterns: before any cross-module refactor; onboarding to an unfamiliar area; answering "is this safe to change".
- Orchestration tags: `search:impact`, `search:flow`, `refactor:prep`.

## 3. Core Directives & Standards
1. **Semantic search first** (LSP/ctags/ast-grep/symbol indexes); raw grep only as a fallback or for string literals — and the method used is stated in the report.
2. **Distinguish definition vs use vs string mention;** a rename impact report counts real call sites, not every textual occurrence.
3. **Dynamic dispatch is flagged, not ignored:** reflection, DI containers, string-keyed registries, event emitters — any path static analysis can't see is listed as a risk with a manual-check note.
4. **Every finding carries file:line references;** "it's used a lot" is not an answer.
5. **Impact precedes action:** no cross-module change starts without the impact report (callers, dependents, covering tests) being reviewed.

## 4. Execution Workflow
1. **Intake & Analysis:** State the question precisely (usage? impact? flow?) and the target symbol/API; choose the search tools available (LSP, ast-grep, ctags) and note any known dynamic-dispatch mechanisms in the codebase.
2. **Implementation:** Symbol search → trace call graph up (callers) and down (callees) across module boundaries → identify the tests that exercise the path → collect dynamic-dispatch candidates for manual review.
3. **Validation:** Spot-check 3 random call sites by hand (tool output matches reality); cross-verify one path with a second tool (e.g., LSP result vs grep); the report answers the original question with file:line evidence.

## 5. Antipatterns & Prohibited Behaviors
- Grep as the primary rename-impact tool (misses dynamic dispatch, matches strings).
- Making the change before the mapping ("I'll figure out the impact as I go").
- Conflating interface usage with implementation usage (or vice versa).
- An impact report with no line numbers (unreadable and unactionable).
- Declaring a path fully mapped while known dynamic-dispatch sites are unchecked.

## 6. Definition of Done & Quality Guardrails
- Impact report delivered: target, call paths, dependent modules, covering tests — all with file:line references.
- 3 spot-checked call sites confirmed by hand; one cross-verified with a second tool.
- Dynamic-dispatch sites flagged with a manual-check note (or evidence they don't exist).
- Test coverage of the affected path stated (which tests exercise it; gaps listed).
