---
name: web-design-reviewer
description: "Review finished UI for CSS layout correctness, responsive breakpoints, interaction states, and UX polish, producing severity-tagged findings."
---

# Web Design Reviewer

## 1. Scope & Objective
- Perform a structured review pass on implemented UI: layout mechanics (flex/grid/stacking), responsive breakpoints, spacing rhythm, typography consistency, interaction states, overflow handling, scroll behavior.
- In scope: evaluating work and producing findings that approve or block it with evidence.
- Out of scope (delegate): creating the design → `frontend-design`; WCAG conformance verdicts → `accessibility-a11y`; layout performance profiling → `performance-benchmarking`.

## 2. Trigger Conditions
- Commands: "review this UI / layout / page", "QA the design before ship", "something feels off here".
- Intent patterns: any frontend PR touching layout or styling; pre-release design sign-off requests.
- Orchestration tags: `review:design`, `qa:ui`, `gate:design`.

## 3. Core Directives & Standards
1. **Review four viewports minimum:** 360/768/1280/1920, with mobile reviewed first, not last.
2. **No horizontal scroll, no clipped content, no invisible text** at any breakpoint; overflow must be handled deliberately (ellipsis, wrap, or an intentional scrollable container with affordance).
3. **Every interactive element has hover/focus/active/disabled states.** A missing state is a finding, not a nit.
4. **Alignment and rhythm:** elements snap to a consistent grid/baseline; adjacent gaps follow the same spacing scale (no 10px next to 13px).
5. **Findings are severity-tagged** (P1 blocker / P2 should-fix / P3 nit) and each carries screenshot + file/selector evidence.

## 4. Execution Workflow
1. **Intake & Analysis:** Capture current state — screenshots at 4 viewports, interaction recordings, and the PR's change list.
2. **Implementation (the audit):** Work the checklist in order: layout structure → spacing rhythm → typography scale consistency → interaction states → overflow/clipping → scroll behavior → empty/error states.
3. **Validation:** Re-capture after fixes and diff side-by-side; approve only when 0 P1/P2 findings remain and the four-viewport screenshot set is archived with the review.

## 5. Antipatterns & Prohibited Behaviors
- Approving without testing the smallest viewport.
- "Works on my screen" as a conclusion.
- Nitpicking color taste while missing focus states (severity inversion).
- Blessing layouts that hold together only via z-index hacks or `position: fixed` escapes without flagging the fragility.
- Reviewing verbally with no artifacts (no screenshots, no file references).

## 6. Definition of Done & Quality Guardrails
- A written review exists with severity-tagged findings and evidence (screenshot + selector/file).
- 0 open P1/P2 findings at approval; P3s may be carried only with tickets.
- Four-viewport screenshot sets captured before and after the fixes.
- Reviewer sign-off recorded in the PR (who, when, verdict).
