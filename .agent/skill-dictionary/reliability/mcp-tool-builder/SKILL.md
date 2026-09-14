---
name: mcp-tool-builder
description: "Build MCP server tools with LLM-optimized descriptions, strict JSON Schema parameters, structured error contracts, and scoped, PII-minimal results."
---

# MCP Tool Builder

## 1. Scope & Objective
- Expose capabilities as Model Context Protocol tools: precise names, LLM-readable descriptions, strict parameter schemas, structured errors, and security-scoped behavior.
- In scope: tool definition and implementation, error contracts, selection testing, security review.
- Out of scope (delegate): interactive widgets on top of tools → `mcp-ui-widgets`; the host client implementation.

## 2. Trigger Conditions
- Commands: "expose X as a tool for the agent", "the agent can't do Y", "wrap this API for MCP".
- Intent patterns: internal capabilities the agent should invoke; agent failing at a task a tool could do; tool review/refactor.
- Orchestration tags: `mcp:tool`, `mcp:build`, `gate:tools`.

## 3. Core Directives & Standards
1. **Names are verb-noun and unambiguous** (`search_invoices`, `create_invoice` — never `process` or `do_thing`); the name plus description is the tool's entire public identity.
2. **Descriptions are written for the LLM:** what it does, when to use it, when NOT to use it, what it returns — this is the only documentation the model has, so it must be precise.
3. **Parameters are strict JSON Schema:** `required` explicit, `enum` for finite choices, `examples` provided; strict mode (no implicit type coercion).
4. **Errors are structured, not stack traces:** error code + human message + retryable flag; raw stack traces or empty failures are prohibited (the agent cannot reason about them).
5. **Security by scope:** no implicit access (each tool declares its scope); results minimize PII; writes are idempotent where possible (idempotency keys); all tools rate-limited.

## 4. Execution Workflow
1. **Intake & Analysis:** Define the capability to expose, the consuming agents, the input domains, and the risk class (read-only vs write); list what must be true for a safe invocation.
2. **Implementation:** Write the schema + description (with examples); implement the handler; define the error contract; add idempotency for writes; add unit tests (direct calls) and a selection test (does a mock LLM pick this tool from the description?).
3. **Validation:** Schema validates in strict mode; selection test passes (correct tool chosen among siblings for representative prompts); error paths return structured errors for every failure mode tested; security review completed (scopes, PII, rate limits documented).

## 5. Antipatterns & Prohibited Behaviors
- God tools with ten modes behind a `mode` flag (the LLM guesses the mode; the schema can't constrain it).
- Descriptions that say "does the thing" (no trigger, no output description).
- Parameters without examples (the model invents the shape).
- Raw stack traces as the error result (unusable to the agent, leaky to the client).
- Write tools without idempotency (retries create duplicates).

## 6. Definition of Done & Quality Guardrails
- Schema + description + examples complete; strict-mode validation passes.
- Selection test passes: a mock LLM picks the correct tool from the description for ≥ representative prompts.
- Error contract implemented and tested for every failure mode.
- Security review archived: scopes, PII minimization, idempotency, rate limits all documented.
