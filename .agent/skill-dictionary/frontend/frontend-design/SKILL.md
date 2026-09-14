---
name: frontend-design
description: "Enforce deliberate typography, aesthetic hierarchy, and anti-generic layout composition when implementing UI surfaces."
---

# Frontend Design

## 1. Scope & Objective
- Define and implement the visual layer of UI surfaces: typographic scale, spacing rhythm, color systems, layout composition, visual hierarchy, and page/component states (empty, loading, error).
- In scope: screens, components, and product/marketing pages built from a design intent or from scratch.
- Out of scope (delegate): WCAG conformance → `accessibility-a11y`; token pipeline generation → `design-token-extractor`; motion implementation → `motion-and-animation`; post-build layout review → `web-design-reviewer`.

## 2. Trigger Conditions
- Commands: "build/design/redo the UI for X", "design a landing page / dashboard / settings screen", "make this look better".
- Intent patterns: "this looks generic / AI-default", "there's no visual hierarchy", "polish the design".
- Orchestration tags: `design:implement`, `ui:new-screen`, `ui:redesign`.

## 3. Core Directives & Standards
1. **One dominant element per view.** Enforce a modular type scale (e.g. 12/14/16/20/28/40px, fluid via `clamp()`); every text size must be picked from the scale.
2. **8pt spacing grid.** Every margin/padding/gap resolves to a token; zero magic pixel values in component code.
3. **Anti-generic layouts.** The centered-hero + three-equal-cards + CTA cliché is forbidden; vary alignment, asymmetry, and rhythm per page; at least one deliberate non-standard layout device (asymmetric grid, sticky column, inline detail rows).
4. **Color discipline.** Neutrals ≥ 70% of painted area; accent used for ≤ 2 distinct purposes per view; dark surfaces defined by intent, not inverted after the fact.
5. **No placeholder content in finished work.** No lorem ipsum, no stock "John Doe" grids — realistic or clearly generated data only.

## 4. Execution Workflow
1. **Intake & Analysis:** Inventory the screen's content types and audience; extract or define design tokens (delegate to `design-token-extractor` when a pipeline is needed); write down the type hierarchy (dominant → secondary → body → caption) before writing code.
2. **Implementation:** Build the type ramp and spacing system first, then layout (grid/flex), then content, then states. Every value references a token; layout variation devices are chosen deliberately, not accidentally.
3. **Validation:** Screenshot at 360/768/1280; run the 3-second hierarchy test ("what matters most?" must be answerable at a glance); grep-audit for hardcoded px/hex outside token definitions and confirm the count is zero.

## 5. Antipatterns & Prohibited Behaviors
- Default indigo-on-white, three equal feature cards, all-caps section headers everywhere, emoji as design elements, decorative aurora gradients.
- Font sizes that don't share a modular ratio; spacing values off the grid "just this once" (13px gaps).
- Centering everything: every header, every card, every CTA.
- Copying one page's layout to the next with no variation (template soup).
- Shipping gray-box placeholders or lorem ipsum and marking the work done.

## 6. Definition of Done & Quality Guardrails
- 100% of visual values (color, spacing, type, radius, shadow) resolve to tokens; grep for hardcoded values in component code returns 0 hits.
- Screens render correctly without overflow at 360/768/1280 viewports.
- Hierarchy passes the 3-second test with evidence (screenshot + one-line note attached).
- Every interactive surface shows hover/focus/active/disabled states (full a11y conformance is verified separately by `accessibility-a11y`).
