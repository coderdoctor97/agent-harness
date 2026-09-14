---
name: accessibility-a11y
description: "Audit and fix UI to WCAG 2.2 AA: contrast, keyboard operability, screen-reader semantics, ARIA correctness, and reduced-motion support."
---

# Accessibility (WCAG 2.2)

## 1. Scope & Objective
- Make UI surfaces conform to WCAG 2.2 Level AA and keep them conformant: contrast, keyboard operability, screen-reader semantics, ARIA correctness, focus management, motion safety.
- In scope: audits plus fixes across HTML/CSS/JS and framework components in the codebase.
- Out of scope (delegate): visual taste and layout composition → `frontend-design`; component test infrastructure → `playwright-component-testing`; theming → `design-token-extractor`.

## 2. Trigger Conditions
- Commands: "make X accessible", "run an a11y audit", "fix the contrast", "the screen reader can't use this".
- Intent patterns: any PR adding or changing interactive UI must pass this skill's validation before merge.
- Orchestration tags: `a11y:audit`, `a11y:fix`, `gate:a11y`.

## 3. Core Directives & Standards
1. **WCAG 2.2 AA floor.** Contrast ≥ 4.5:1 body text, ≥ 3:1 large text and UI components (SC 1.4.3 / 1.4.11); focus visible on every interactive element (SC 2.4.7 / 2.4.13).
2. **Native semantics before ARIA.** `<button>` beats `<div role="button">`; ARIA only where native elements cannot express the pattern, and every ARIA attribute must have a working handler, including keyboard.
3. **100% keyboard operable.** Every flow completable with Tab/Shift+Tab/Enter/Escape alone; focus order follows visual order; no trap without an Escape path (modals trap and restore focus on close).
4. **`prefers-reduced-motion` honored.** Static or opacity-only fallbacks — never "the same animation, slower".
5. **Complete naming.** Every input has a programmatically associated label; every icon button has an accessible name; decorative images are `alt=""` / `aria-hidden`.

## 4. Execution Workflow
1. **Intake & Analysis:** Run axe-core (or equivalent) against the affected routes; produce a violations list plus a manual checklist (keyboard, screen reader) — automated tools miss a substantial share of real a11y issues, so the manual list is mandatory.
2. **Implementation:** Fix in priority order: (a) keyboard/focus, (b) labels/names, (c) contrast, (d) ARIA correctness, (e) motion. Prefer structural HTML fixes over ARIA band-aids.
3. **Validation:** axe-core reports 0 violations at AA; keyboard walkthrough of the top 5 flows passes; screen-reader smoke test (NVDA/VoiceOver) of the primary flow is documented; contrast report shows every pair at or above threshold.

## 5. Antipatterns & Prohibited Behaviors
- `role="button"` on a div with no keydown handler; positive `tabindex` values anywhere.
- "Fixing" contrast by making text bold instead of changing the color value.
- `aria-label` that misdescribes or duplicates visible text; ARIA attributes with no working handler behind them.
- Focus traps without Escape exit or without restoring focus on close.
- Declaring done on a green axe run without the keyboard and screen-reader walkthroughs.

## 6. Definition of Done & Quality Guardrails
- axe-core: 0 AA violations on every affected route (report attached to the change).
- Contrast report: 100% of text and UI-component pairs meet the required ratio.
- Keyboard walkthrough: 5/5 top flows completable, with notes recorded.
- Screen-reader smoke test of the primary flow documented (tool, OS, findings).
- CI guard: the a11y scan is wired in for the affected package so regressions fail builds.
