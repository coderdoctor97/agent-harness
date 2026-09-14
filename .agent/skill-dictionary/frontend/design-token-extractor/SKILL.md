---
name: design-token-extractor
description: "Extract design tokens from sources (Figma, CSS, brand guides) into a canonical token schema and generated CSS variables with full traceability."
---

# Design Token Extractor

## 1. Scope & Objective
- Extract, normalize, and publish design tokens: colors, spacing, radii, typography, and shadows — from Figma, existing CSS, or brand documentation — into a canonical token schema and generated outputs (CSS custom properties + typed exports).
- In scope: token pipelines, token naming, theme variants (light/dark).
- Out of scope (delegate): consuming tokens in components → `frontend-design`; runtime theming APIs → `component-composition`.

## 2. Trigger Conditions
- Commands: "extract tokens from X", "set up our design tokens", "we have 400 hardcoded hex values", "add dark mode".
- Intent patterns: new brand or theme, hardcoded-value cleanup, token pipeline bootstrap.
- Orchestration tags: `design:tokens`, `theme:setup`.

## 3. Core Directives & Standards
1. **Three-layer token model:** primitives (raw values: `blue-500`) → semantic (role: `color-action-primary`) → component aliases (optional: `button-bg`). Components reference semantic tokens, never primitives.
2. **Every token has name (kebab-case), value, category, and description;** the token set validates against the W3C DTCG (`design-tokens`) JSON schema.
3. **Traceability:** every token maps to its source (Figma variable ID, CSS file, or brand doc section); untraceable values are not added.
4. **Outputs are generated, never hand-edited:** CSS custom properties and typed JS/TS exports come from the pipeline (e.g., Style Dictionary); the pipeline is CI-checkable.
5. **Theme variants use the semantic layer:** dark mode re-maps semantic tokens to different primitives — component code never branches on theme.

## 4. Execution Workflow
1. **Intake & Analysis:** Identify the source of truth; audit the codebase for distinct hardcoded values (colors, spacing, radii, font sizes); count and cluster them.
2. **Implementation:** Extract → deduplicate → assign names per the 3-layer model → add descriptions → build the pipeline that emits CSS variables + typed exports; wire generation into the build and CI.
3. **Validation:** Schema validation passes; a component sweep replaces hardcoded values with tokens (grep for raw hex/px in component code returns 0); theme switching (light/dark) renders with no unstyled elements.

## 5. Antipatterns & Prohibited Behaviors
- Per-component token proliferation (`buttonPrimaryBgHoverDark` as a top-level primitive).
- Naming tokens by hue (`buttonBlue`) instead of role (`color-action-primary`).
- Skipping the semantic layer, forcing dark mode to rewrite component code.
- Tokens without descriptions (the next team member cannot use them).
- Hand-editing generated output files.

## 6. Definition of Done & Quality Guardrails
- 100% of UI color/spacing/radius/typography values live in the token schema.
- 0 hardcoded values in app component code (verified by grep audit).
- CSS custom properties cover 100% of token usages; generation is deterministic and CI-verified.
- Theme toggle test passes (light/dark render check with no unstyled fallbacks).
