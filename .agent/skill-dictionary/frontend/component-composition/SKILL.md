---
name: component-composition
description: "Design component APIs using compound components, context, polymorphic slots, and strict typing to eliminate prop drilling and speculative APIs."
---

# Component Composition

## 1. Scope & Objective
- Design and refactor component APIs: compound component patterns, context for shared state, polymorphism, slots/children, and strict TypeScript boundaries — eliminating prop drilling and over-specified props.
- In scope: public API shape of component families; internal composition strategy.
- Out of scope (delegate): visual design → `frontend-design`; test strategy → `playwright-component-testing`.

## 2. Trigger Conditions
- Commands: "refactor this component's API", "stop the prop drilling", "this component has 14 props", "make X composable".
- Intent patterns: mega-props (10+), deep trees passing the same object 4 levels, components only usable in one fixed shape.
- Orchestration tags: `ui:api`, `refactor:components`.

## 3. Core Directives & Standards
1. **Compound + context over mega-props:** components with more than ~8 props and strong sibling relationships (Tabs, Menu, Dialog, Form) become compound components sharing state via context.
2. **Polymorphism is explicit:** an `as`/`component` prop with discriminated-union TS types (never a loose `React.ElementType` escape hatch that erases prop types).
3. **Content via children/slots,** not `title`/`subtitle`/`bodyText` prop families; render logic stays with the caller.
4. **No speculative API:** every public prop must be used by at least two consumers (or justified in a comment); unknown props are not forwarded blindly.
5. **Strict boundaries:** new component APIs typecheck under `strict`; logic-only parts may be extracted headless (no rendering) and reused separately.

## 4. Execution Workflow
1. **Intake & Analysis:** Map the current API: props, consumers, coupling (which props are always passed together, which trees share state); identify the drilling paths.
2. **Implementation:** Extract shared state into a context provider; split the mega-component into a compound family; introduce slots/children for content; add strict TS types (discriminated unions, `never` exhaustiveness checks).
3. **Validation:** Consumer migration compiles clean under `strict` with 0 `any` at new boundaries; no prop-drilling path deeper than 2 levels remains; API documented with usage examples per compound member.

## 5. Antipatterns & Prohibited Behaviors
- `children` as a catch-all for every possible content variant (the API became an undocumented protocol).
- Re-creating context values on every render without memoization where the context is broad.
- `forwardRef` by default for everything instead of explicit, documented ref targets.
- Leaking internal implementation state into the public API "for flexibility".
- Blindly forwarding `...rest` props to a DOM node (garbage in, HTML warnings out).

## 6. Definition of Done & Quality Guardrails
- Prop depth reduced to ≤ 2 levels for the refactored tree (verified by consumer audit).
- New API documented with working usage examples for every compound member.
- Consumers compile under strict TS with 0 `any` at the new boundaries.
- No public prop is used by exactly one consumer without a written justification.
