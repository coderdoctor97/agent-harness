---
name: mcp-ui-widgets
description: "Build interactive UI widgets for MCP clients: self-contained HTML resources with a sandboxed message protocol and graceful text fallbacks."
---

# MCP UI Widgets

## 1. Scope & Objective
- Build interactive UI micro-frontends delivered by MCP servers to MCP clients via the MCP-UI capability: sandboxed HTML widgets, resource templates, and a message protocol for user actions.
- In scope: widget markup/CSS/JS, action protocol, fallback content, schema versioning.
- Out of scope (delegate): the MCP tool definitions that feed widgets → `mcp-tool-builder`; host application design → `frontend-design`.

## 2. Trigger Conditions
- Commands: "add a widget to the MCP response", "show an interactive chart in the chat client", "MCP-UI integration for X".
- Intent patterns: tool results that benefit from interactivity (pickers, confirmations, inline editors, live charts) rather than plain text.
- Orchestration tags: `mcp:widget`, `mcp:ui`.

## 3. Core Directives & Standards
1. **Self-contained HTML resources** (resource templates): inline styles, no dependence on host CSS/JS; no external network requests by default (no CDNs inside widgets).
2. **Sandbox discipline:** widgets never touch the host DOM; all data exchange goes through the documented message protocol (action → new tool call or client message); CSP-clean markup only.
3. **Graceful degradation:** every widget ships a plain-text fallback summary; the server returns it alongside the widget, and the fallback must stand alone.
4. **Bounded artifacts:** widget HTML < 100 KB; schema versioned; widget state is minimal (prefer round-tripping to the server over client-side state machines).
5. **Accessibility inside the widget:** semantic HTML, keyboard operability, contrast — widgets are UI and inherit `accessibility-a11y` standards.

## 4. Execution Workflow
1. **Intake & Analysis:** Define the widget's purpose, its inputs (derived from the tool result), and its outputs (which user actions map to which tool calls); decide what must work with text only.
2. **Implementation:** Build the self-contained HTML (inline CSS, minimal JS); implement the action message protocol; write the text fallback; version the widget schema.
3. **Validation:** Widget renders in the reference MCP client; CSP audit shows 0 violations; every user action round-trips to the correct tool call; fallback text renders correctly when the widget is disabled.

## 5. Antipatterns & Prohibited Behaviors
- Widgets that depend on host CSS classes or global JS (break in every client).
- Third-party CDN scripts inside widgets (uncontrolled supply chain in a sandbox).
- No text fallback — users on clients without UI capability see nothing.
- Unbounded widget payloads (entire datasets embedded as HTML tables).
- Treating a widget as a full web app (routing, persistence, auth) instead of a focused interaction.

## 6. Definition of Done & Quality Guardrails
- Widget plus fallback both verified in the reference MCP client (screenshots of each).
- CSP audit: 0 violations; no external network calls.
- Action protocol documented (message shapes, idempotency of re-dispatch).
- Widget schema versioned and validated by a test.
