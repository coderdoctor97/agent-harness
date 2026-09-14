---
name: arch-diagram-generator
description: "Author verifiable Mermaid/C4 diagrams (context, containment, component, sequence, state) with labeled edges, bounded node counts, and CI render checks."
---

# Architecture Diagram Generator

## 1. Scope & Objective
- Produce architecture diagrams that stay true to the system: C4 zoom levels, sequence and state diagrams, ER views — in Mermaid, render-verified, and maintained in the repo.
- In scope: diagram modeling, labeling, render verification, audience fit.
- Out of scope (delegate): the decision text around the diagram → `adr-author`; implementation.

## 2. Trigger Conditions
- Commands: "diagram X", "we need a C4 diagram", "draw the sequence for Y", "explain the architecture to the new hire".
- Intent patterns: architecture docs, design reviews, onboarding material, incident explanations.
- Orchestration tags: `docs:diagram`, `arch:visualize`.

## 3. Core Directives & Standards
1. **One concern per diagram;** C4 discipline: start at context, drill to containment/component only when the question requires it — no single diagram for everything.
2. **Bounded complexity:** ≤ 10 primary nodes per diagram; if the system is bigger, split into zoom levels rather than shrinking the fonts.
3. **Every edge is labeled** with protocol and purpose ("HTTP/JSON", "Kafka: order-events", "gRPC: authz check") — an unlabeled edge is an unexplained dependency.
4. **Diagrams live in the repo as Mermaid source** and render-check in CI (mermaid-cli) — image-only diagrams that can't be diffed or verified are prohibited.
5. **Verifiability is the standard:** a peer must be able to trace one real request through the diagram and match it to the code (spot-check 3 components against reality).

## 4. Execution Workflow
1. **Intake & Analysis:** Identify the audience and the question the diagram must answer; choose the level (context/containment/component/sequence/state/ER); list the real entities and flows (from code, not memory).
2. **Implementation:** Model entities and edges; draft the Mermaid; render it; simplify (cut noise, merge trivial nodes); label every edge; add a title + one-line "what this shows" + legend if types mix.
3. **Validation:** Renders in Mermaid (CI check passes); peer trace test: one request followed through the diagram matches the code; 0 unlabeled edges; 3 components spot-checked against the codebase.

## 5. Antipatterns & Prohibited Behaviors
- The one-diagram-to-rule-them-all (context + components + sequence in a 30-node hairball).
- Diagrams as legacy art: no render check, never updated, quietly wrong.
- Unlabeled edges ("it obviously calls the other thing").
- PNG-only diagrams in docs (undiffable, unbuildable, rot by default).
- Modeling the ideal architecture instead of the real one (with no "planned" marking).

## 6. Definition of Done & Quality Guardrails
- Mermaid source in the repo; CI render check passes.
- ≤ 10 primary nodes; 100% of edges labeled.
- Peer trace test passed (one flow followed and matched to code).
- Diagram versioned alongside the ADR/feature it documents; "planned vs current" marked where they differ.
