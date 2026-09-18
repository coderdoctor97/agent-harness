# Local web UI

Submit a task, watch the agent plan and execute it step by step, then read the
deliverable and the files it produced — all in your browser, all on your machine.

The UI is a *view* over the same `AgentHarness` the CLI runs: same config, same
plugins, same recovery behaviour. Nothing is uploaded anywhere except the prompts
and tool inputs your own run sends to the LLM provider.

- Design rationale and alternatives: `documentations/adr/ADR-001-local-web-ui.md`
- Plan that delivered it: `planning/plan-6-web-ui/plan.md` (P6)

---

## Windows: one-click use

Two batch files sit in the project root. Neither needs administrator rights, and
both are safe to run more than once.

### From File Explorer

1. **First time:** double-click **`setup.bat`**.
   It checks for Git and Python 3.9+, creates `.venv`, installs the project with
   the web UI and dev extras, copies `.env.example` to `.env`, and writes a default
   `config.yaml` if you do not have one. If anything fails, the window stays open
   and prints what to fix; a missing runtime is reported with the exact download
   link.
2. **Add your API key:** open `.env` in Notepad and set it —
   `OPENAI_API_KEY=sk-...` (or point `llm.api_key_env` at whichever variable your
   provider uses).
3. **Every day after that:** double-click **`start.bat`**.
   It verifies the install, starts the local server, and opens your default
   browser at the UI. Leave the black window open while you work: **Ctrl+C** in it
   stops the server cleanly, and closing it stops the server too.

### From a terminal

```bat
cd C:\path\to\agent-harness
setup.bat                :: once
start.bat                :: start the UI and open the browser
start.bat /port 8899     :: use a different port
start.bat /noopen        :: start the server, do not open a browser
start.bat /cli           :: run tasks in the terminal instead of the UI
start.bat /help          :: usage summary
```

`setup.bat /nopause` runs unattended (it never waits for a key), which is what CI
would use.

### What the scripts do *not* do

They never install a runtime for you, never edit `config.yaml` that already
exists, never overwrite an existing `.env`, and never leave a background service
running after you close the window.

---

## Any platform: running the server directly

```bash
pip install "agent-harness[web]"     # FastAPI + uvicorn, optional extra
python -m agent_harness.web          # http://localhost:8765, browser opens
python -m agent_harness.web --port 9000 --no-browser
python -m agent_harness.web --help
```

Or from Python, which is what `examples/web_ui.py` does:

```bash
python examples/web_ui.py --probe                  # list the API routes
python examples/web_ui.py --task "summarise X"     # run one task on the console
```

If the extra is not installed, the launcher says so and prints the exact command;
the rest of the project keeps working without it.

---

## Using the UI

| Area | What it does |
|---|---|
| **Task box** | Type a task; **Ctrl+Enter** submits. Three preset buttons fill in example prompts. The 20,000-character limit is the same one the harness enforces. |
| **Plan & steps** | One row per step: its tool, priority, dependencies, status badge and duration. Rows update live as the run progresses, so a retry is visible as it happens. |
| **Execution log** | The raw event stream (plan start, step start/complete/failed, recovery, plan complete), timestamped. This is the honest record — the step list is a summary of it. |
| **Deliverable** | Three tabs: the assembled **Output**, the SPEC-006 **Report**, and the **Metrics** (steps, retries, duration, LLM calls, tokens, estimated cost). |
| **Output files** | Everything the run wrote under your output directory, newest first, with size and time. Click to open a file in a new tab. |
| **Recent tasks** | Task history for this server session. Click one to re-open its log, steps and result. |
| **Header** | Live provider, model, output directory, and whether a credential is configured — never the value itself. |

### Ports and configuration

Precedence is the project's usual one: **flag > environment > config > default**.

| Setting | Flag | Environment | Default |
|---|---|---|---|
| Bind address | `--host` | `AGENT_HARNESS_WEB_HOST` | `127.0.0.1` |
| Port | `--port` (or `start.bat /port N`) | `AGENT_HARNESS_WEB_PORT` | `8765` |
| Browser auto-open | `--no-browser` (or `start.bat /noopen`) | `AGENT_HARNESS_WEB_NO_BROWSER=1` | open |
| Config file | `--config` | `AGENT_HARNESS_CONFIG` | `./config.yaml` |

If the port is busy the server picks the next free one and says so in the banner.
A `web:` section in `config.yaml` will be honoured once SPEC-006 § 1 accepts one
(see SCR-P6-1 in the plan); today the loader rejects unknown sections, so use the
flag or the environment variable.

### Keyboard and accessibility

Everything is reachable with Tab and Enter alone; the task box, presets, tabs,
history and file links are native controls with visible focus. The log is a polite
live region and errors are announced assertively. Animations stop under
`prefers-reduced-motion`. Contrast targets WCAG 2.2 AA.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `[ERROR] web UI dependencies are not installed` | Install the extra: `pip install "agent-harness[web]"` (on Windows: `.venv\Scripts\python.exe -m pip install --editable ".[web]"`). |
| Browser opens but the page never loads | The server probably is not listening yet or died — check the console window. `start.bat /noopen` plus a manual refresh distinguishes the two. |
| `no free port in 8765-8784` | Something is holding every nearby port. Pass `--port` with a free one. |
| Task fails immediately with `CONFIG_VALIDATION_FAILED` | No API key. Add it to `.env`, then restart the server (config is read at startup). |
| Header shows `missing` for the credential | The environment variable named by `llm.api_key_env` is not set *for the server process*. On Windows, a variable set after the server started is not visible to it. |
| A run shows fewer steps than expected | Read the log: a step whose dependency failed is **skipped**, and skipped steps appear in the list with a `warn` badge. |
| Files do not appear under Output files | Check the output directory in the header; the panel lists that directory only, and refreshes every few seconds. |
| Port 8765 is taken by something you do not recognise | The server binds loopback only. If you launched it with `--host 0.0.0.0`, anything on your network can reach it — stop it and use the default. |

---

## Security notes

- **Loopback by default.** `--host 0.0.0.0` exposes the agent to your network: anyone
  who can reach the port can run tasks with your API key. There is no authentication
  by design (single local user); do not bind a public interface.
- **Secrets stay server-side.** The UI shows whether a key exists, never its value,
  and events carry no environment values (SPEC-006 § 3.4).
- **File access is contained.** Artifact reads resolve inside
  `execution.output_dir`; traversal and symlink escapes are refused, and files over
  8 MB are not served.
- **Shell and code tools keep their guards.** The UI does not bypass
  `security.allow_shell`, the code sandbox, or any tool's own checks — it calls the
  same registry the CLI does.

---

## API

The HTTP surface is documented from the code itself:

- Interactive docs: `http://localhost:8765/api/docs`
- OpenAPI 3.1 document: `http://localhost:8765/api/openapi.json`

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | the UI |
| `GET` | `/api/health` | server and non-secret config summary |
| `GET` | `/api/tools` | the registry, as `--list-tools` sees it |
| `POST` | `/api/tasks` | submit a task |
| `GET` | `/api/tasks` | task history |
| `GET` | `/api/tasks/{id}` | steps, metrics, output, report |
| `GET` | `/api/tasks/{id}/events?since=N` | event batch from a cursor |
| `GET` | `/api/tasks/{id}/stream` | the same events as Server-Sent Events |
| `GET` | `/api/artifacts` | files under the output directory |
| `GET` | `/api/artifacts/{path}` | one file's bytes |

Polling and streaming read the same log, so a client may mix them freely: keep the
highest `seq` you have seen and pass it as `since`.
