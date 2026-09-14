---
name: motion-and-animation
description: "Implement UI motion (GSAP/Framer Motion) with transform-only animations, scroll triggers, layout-safe transitions, and reduced-motion fallbacks."
---

# Motion & Animation

## 1. Scope & Objective
- Implement motion in UI: entrance/exit transitions, scroll-triggered sequences, layout (FLIP) animations, micro-interactions — with GSAP or Framer Motion.
- In scope: any animated behavior in product UI, from button presses to page transitions.
- Out of scope (delegate): what to animate and the visual language → `frontend-design`; reduced-motion conformance audits → `accessibility-a11y` (this skill ships the fallbacks).

## 2. Trigger Conditions
- Commands: "animate X", "add a page transition", "make this section reveal on scroll".
- Intent patterns: hero motion, onboarding polish, dashboard number changes, list reordering animations.
- Orchestration tags: `ui:motion`, `ui:transition`.

## 3. Core Directives & Standards
1. **Animate `transform` and `opacity` only.** Never width/height/top/left — layout-affecting properties cause reflow and jank.
2. **Timing discipline:** 150–400ms for UI transitions, ease-out for entrances; nothing exceeds 600ms unless it is a deliberate, skippable sequence.
3. **`prefers-reduced-motion` respected:** every animation has a static or opacity-only fallback, checked via the media query, not by luck.
4. **No layout thrash:** batch reads and writes; scroll-driven work is frame-throttled (GSAP `ScrollTrigger`, Framer `useScroll`) — never raw `onscroll` + layout.
5. **Every animated element has a defined resting state;** interrupted animations settle to the resting state, never stuck mid-value.

## 4. Execution Workflow
1. **Intake & Analysis:** Write the motion spec before code: element, trigger (hover/scroll/mount/state), from→to, duration, easing, and interruption behavior.
2. **Implementation:** Compose timelines (GSAP) or variants (Framer); use ScrollTrigger/`useScroll` for scroll-linked motion; FLIP for layout changes — never animate the layout properties themselves.
3. **Validation:** 60fps on target hardware (DevTools performance trace, mid-tier device); reduced-motion path renders the static equivalent; zero console warnings about interrupted/orphaned animations; CLS < 0.05 on the animated page.

## 5. Antipatterns & Prohibited Behaviors
- Animating width/height/top/left (reflow every frame).
- Bounce/elastic easing on everything; 2-second animations on button presses.
- Scroll-jacking (hijacking user scroll) without a visible way out.
- Applying parallax to every element for "wow".
- Ignoring `prefers-reduced-motion`, or merely slowing the animation down.

## 6. Definition of Done & Quality Guardrails
- 60fps on target hardware for all animations (performance trace attached).
- Reduced-motion users get static equivalents (verified via DevTools emulation).
- The motion spec in the PR description matches the implementation (triggers, durations, easings).
- CLS < 0.05 measured on the animated page; no stuck mid-animation states after interruption.
