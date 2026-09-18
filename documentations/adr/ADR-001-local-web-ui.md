# ADR-001 — A local web UI for the agent harness

- **Status:** Accepted
- **Date:** 2026-09-18
- **Deciders:** Agent 6 (Web Surface), on the user's explicit instruction
- **Spec context:** PRD G8 (*"minimal CLI interface and optional lightweight web
  UI"*, P2) and PRD § 16 (*Web UI — Deferred: Flask/FastAPI front-end with step
  visualization*) · PRD G6 (*runs entirely locally*) · SPEC-003 § 2.1 (the hook
  seam was reserved for "how a future web UI will attach")

## Context

The harness ships a complete CLI: one prompt in, a plan executed with recovery,
an assembled deliverable out, structured logs and an execution report. The PRD
defers a web UI as future work and names Flask/FastAPI as the intended shape.

The user asked for `setup.bat` and `start.bat` so the project can be started with
one click on Windows, and then specified the gap those scripts exposed: a
browser UI to *enter a task, watch it execute, and read the results* — built in
Python, on this project's own stack, not a generic Node web template.

Two facts shape the decision. First, the interesting part of a run is a
*stream*: steps start, fail, recover and complete over minutes, and the existing
`progress` seam (SPEC-003 § 2.1) already emits exactly those events — the spec
even says a future web UI would attach there without orchestrator changes.
Second, the project is local-first: a single user, one machine, no deployment
story, no multi-tenant concerns.

## Decision

Add an **optional** `agent_harness.web` package: a FastAPI server that exposes the
frozen harness API over HTTP and streams progress events to a plain
HTML/CSS/JS page served from the same process.

Specifically:

1. **FastAPI + uvicorn, behind a `[web]` extra.** `pip install "agent-harness[web]"`.
   The core package never imports the web layer, so a CLI-only install is unchanged
   and the extra cannot break it.
2. **The browser talks to a task service, not to the harness.** `TaskRunner` owns
   one worker thread, one harness per task, and the event log. HTTP handlers are
   thin projections of that state.
3. **Server-Sent Events for the live log, cursor polling as an equal transport.**
   Both read the same server-side log; a proxy that buffers `text/event-stream`
   degrades to polling rather than breaking.
4. **No build step and no CDN.** Tokens, CSS, HTML and JS ship as package data and
   are served by the app. The UI works offline, is reviewable by reading it, and
   adds no Node toolchain to a Python project.
5. **Bind to `127.0.0.1` by default**, with an explicit, documented override.
6. **Windows scripts are thin.** `setup.bat` provisions, `start.bat` launches and
   prints the URL; neither contains business logic that could drift from the app.

## Alternatives considered

| Alternative | Why not |
|---|---|
| **Node/React/Vite front end** | Adds a second runtime, a build step and a lockfile to a project whose PRD goal G6 is "runs entirely locally" with no extra infrastructure. It also doubles the review surface for a single-user tool, and the framework buys nothing here: the UI is one form, one step list and one log. |
| **Streamlit / Gradio** | Fast to write, but they own the page lifecycle and re-run the script per interaction, which fights a long-running background task with a live event stream. Both also bring a large dependency tree for a 700-line UI. |
| **Textual / Rich TUI** | Already partly built (the CLI renders Rich progress). It does not satisfy "read the report in a browser", loses history, and is harder to scan during a long run than a page that keeps the whole log. |
| **A separate `jarvis-web` process reading the log files** | Introduces a second source of truth and a file-watching race. The launcher would have to coordinate two processes and a shutdown order. |
| **A full server-rendered multi-page app (Jinja templates)** | More requests and more server state for no benefit; the interesting updates are incremental, which is what SSE plus a small client gives. |
| **Write `setup.bat`/`start.bat` against a Node template** (the request's literal shape) | Nothing in this repository is JavaScript; the scripts would check for a runtime the project does not use and launch a server that does not exist. The user rejected this explicitly. |

## Consequences

**Positive**

- One command (`start.bat`) takes a Windows user from clone to a working UI; the
  browser opens itself once the socket is accepting, so a slow start is never a
  blank tab.
- The UI and the CLI execute through the same `AgentHarness` with the same config,
  plugins and recovery behaviour — the UI cannot drift into a second code path.
- The event log makes a run *inspectable after the fact*: a reconnect resumes from
  a cursor instead of replaying, and the same data is available over a plain JSON
  endpoint for scripting.
- Accessibility and design rules are enforced by tests (token discipline, labels,
  focus, reduced motion, no CDN), so the UI does not quietly rot.

**Negative / accepted costs**

- A second surface to keep working: new routes, new tests, a new optional extra.
  Mitigation: the web package is small, has no core dependencies in the other
  direction, and its tests are part of the default suite when the extra is installed.
- One worker means two submissions serialize. Accepted: this is a single-user local
  tool, and the alternative (a shared registry and context store across threads)
  would violate SPEC-005 § 5's per-instance reuse guarantee.
- `setup.bat`/`start.bat` cannot be executed in CI on Linux. Mitigation: static
  tests assert their structure (CRLF, `pushd "%~dp0"`, tagged status lines,
  existence-guarded writes, the exact entry point), and a Windows runner remains
  the one acknowledged gap.

**Security posture**

The server binds loopback, serves one user, and never returns secret material:
`/api/health` reports the provider *name* and whether a key is configured, never a
value (SPEC-006 § 3.4). Artifact reads are confined to `execution.output_dir` by a
check on the **resolved** path, which also catches symlink escapes, and files over
8 MB are refused. A task prompt is bounded by the same 20,000-character limit the
harness enforces.

## Revisit triggers

- A second concurrent user, or any need to bind beyond loopback by default →
  authentication, CSRF protection and per-user task isolation become requirements.
- The step list outgrowing one screen (dozens of parallel steps) → a graph/timeline
  view instead of a list.
- A hosted/multi-process deployment → the in-memory event log becomes a real
  broker, and the runner moves out of the web process.
- SPEC-006 § 1 gaining a `web:` section (SCR-P6-1) → the launcher already reads it;
  the ADR's port/host defaults become configuration rather than convention.
