/* =============================================================================
   Agent Harness — UI behaviour
   Skills: frontend/component-composition (small composable renderers, one state
   object, no prop drilling), frontend/form-management (one validation source,
   guarded submission, server errors mapped onto fields),
   frontend/accessibility-a11y (live regions, focus handling, keyboard paths).

   Transport: Server-Sent Events for the live log, with a cursor-based polling
   fallback. Both read the same server-side event log, so a buffering proxy
   degrades the experience instead of breaking it.
   ========================================================================== */

const API = "/api";
const POLL_INTERVAL_MS = 900;
const STEP_STATUS_BADGE = {
  pending: "badge--idle",
  running: "badge--running",
  retrying: "badge--warn",
  success: "badge--success",
  completed: "badge--success",
  failed: "badge--failed",
  skipped: "badge--warn",
};
const EVENT_LABEL = {
  plan_start: "plan",
  step_start: "step",
  step_complete: "done",
  step_failed: "fail",
  recovery: "retry",
  plan_complete: "plan",
  task_finished: "task",
};

const state = {
  activeTaskId: null,
  cursor: 0,
  stream: null,
  poller: null,
  terminal: false,
};

const el = (id) => document.getElementById(id);

/* -- small renderers ------------------------------------------------------ */

function badge(status) {
  const cls = STEP_STATUS_BADGE[status] || "badge--idle";
  const node = document.createElement("span");
  node.className = `badge ${cls}`;
  node.textContent = status || "pending";
  return node;
}

function formatDuration(ms) {
  if (!ms) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderSteps(steps) {
  const list = el("steps");
  list.textContent = "";
  if (!steps.length) {
    const empty = document.createElement("li");
    empty.className = "artifacts__empty";
    empty.textContent = "Waiting for the plan…";
    list.append(empty);
    return;
  }
  steps.forEach((step, index) => {
    const item = document.createElement("li");
    item.className = "step";

    const ordinal = document.createElement("span");
    ordinal.className = "step__index";
    ordinal.textContent = String(index + 1).padStart(2, "0");

    const body = document.createElement("div");
    body.className = "step__body";
    const description = document.createElement("span");
    description.className = "step__description";
    description.textContent = step.description || step.id;
    body.append(description);

    const meta = document.createElement("div");
    meta.className = "step__meta";
    if (step.tool) meta.append(Object.assign(document.createElement("span"), { textContent: step.tool }));
    if (step.priority) meta.append(Object.assign(document.createElement("span"), { textContent: step.priority }));
    if (step.depends_on && step.depends_on.length) {
      meta.append(Object.assign(document.createElement("span"), { textContent: `after ${step.depends_on.join(", ")}` }));
    }
    if (meta.childNodes.length) body.append(meta);

    if (step.error) {
      const error = document.createElement("span");
      error.className = "step__error";
      error.textContent = step.error;
      body.append(error);
    }

    const trailing = document.createElement("div");
    trailing.append(badge(step.status));
    const duration = document.createElement("div");
    duration.className = "step__duration";
    duration.textContent = formatDuration(step.duration_ms);
    trailing.append(duration);

    item.append(ordinal, body, trailing);
    list.append(item);
  });
}

function renderEvent(event) {
  const row = document.createElement("div");
  row.className = "log__row";
  const time = document.createElement("span");
  time.className = "log__time";
  time.textContent = (event.at || "").slice(11, 19) || "--:--:--";
  const kind = document.createElement("span");
  kind.className = "log__kind";
  kind.textContent = EVENT_LABEL[event.event] || event.event;
  const text = document.createElement("span");
  text.className = "log__text";
  text.textContent = describeEvent(event);
  row.append(time, kind, text);
  return row;
}

function describeEvent(event) {
  const f = event.fields || {};
  switch (event.event) {
    case "plan_start":
      return `plan ${f.plan_id || ""} accepted`;
    case "step_start":
      return `${f.step_id || ""} → ${f.tool || "tool"} starts`;
    case "step_complete":
      return `${f.step_id || ""} ${f.success === false ? "failed" : "finished"} in ${formatDuration(Number(f.duration_ms) || 0)}`;
    case "step_failed":
      return `${f.step_id || ""} failed: ${f.error || "unknown error"}`;
    case "recovery":
      return `${f.step_id || ""} recovering via ${f.strategy || f.level || "retry"}`;
    case "plan_complete":
      return `plan ${f.status || "finished"}`;
    case "task_finished":
      return `task ${f.status || ""}`;
    default:
      return Object.entries(f).map(([k, v]) => `${k}=${v}`).join(" ") || "event";
  }
}

function appendEvents(events, { replace = false } = {}) {
  const log = el("log");
  if (replace) log.textContent = "";
  if (replace && !events.length) {
    const empty = document.createElement("span");
    empty.className = "log__empty";
    empty.textContent = "Events will stream here.";
    log.append(empty);
    return;
  }
  events.forEach((event) => log.append(renderEvent(event)));
  log.scrollTop = log.scrollHeight;
}

function renderMetrics(metrics) {
  const grid = el("metrics-grid");
  grid.textContent = "";
  if (!metrics) return;
  const rows = [
    ["Steps succeeded", `${metrics.successful_steps}/${metrics.total_steps}`],
    ["Recovered", metrics.recovered_steps],
    ["Skipped", metrics.skipped_steps],
    ["Retries", metrics.total_retries],
    ["Duration", formatDuration(metrics.total_duration_ms)],
    ["LLM calls", metrics.llm_calls],
    ["Tokens", metrics.llm_tokens_used],
    ["Est. cost", `$${Number(metrics.llm_estimated_cost || 0).toFixed(4)}`],
  ];
  rows.forEach(([label, value]) => {
    const cell = document.createElement("div");
    cell.className = "metric";
    const l = document.createElement("div");
    l.className = "metric__label";
    l.textContent = label;
    const v = document.createElement("div");
    v.className = "metric__value";
    v.textContent = String(value);
    cell.append(l, v);
    grid.append(cell);
  });
}

function renderResult(task) {
  const panel = el("result-panel");
  const hasResult = Boolean(task.final_output || task.report || task.metrics);
  panel.hidden = !hasResult;
  if (!hasResult) return;

  const output = el("output");
  output.textContent = "";
  if (task.final_output) {
    const pre = document.createElement("pre");
    pre.className = "output__prose";
    pre.textContent = task.final_output;
    output.append(pre);
  } else {
    const placeholder = document.createElement("p");
    placeholder.className = "output__placeholder";
    placeholder.textContent = "The run produced no assembled output.";
    output.append(placeholder);
  }

  el("report").querySelector("pre").textContent = task.report || "No report was rendered.";
  renderMetrics(task.metrics);
  el("result-files").textContent = task.files_created && task.files_created.length
    ? `${task.files_created.length} file${task.files_created.length === 1 ? "" : "s"} created`
    : "";
}

function setRunStatus(status) {
  const node = el("run-status");
  node.textContent = status;
  node.className = `badge ${STEP_STATUS_BADGE[status] || "badge--idle"}`;
  const terminal = ["completed", "partial", "failed"].includes(status);
  el("live").hidden = terminal;
}

function showError(code, message) {
  const box = el("error");
  el("error-code").textContent = code || "";
  el("error-message").textContent = message || "";
  box.hidden = !message;
}

/* -- data access ---------------------------------------------------------- */

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = (body && body.detail) || {};
    const error = new Error(detail.message || `request failed (${response.status})`);
    error.code = detail.code || `HTTP_${response.status}`;
    throw error;
  }
  return body;
}

async function loadHealth() {
  try {
    const health = await api("/health");
    el("health-provider").textContent = health.provider;
    el("health-model").textContent = health.model;
    el("health-output").textContent = health.output_dir;
    const key = el("health-key");
    key.textContent = health.api_key_configured ? "configured" : "missing";
    key.classList.toggle("fact__value--warn", !health.api_key_configured);
  } catch (error) {
    showError("HEALTH_FAILED", error.message);
  }
}

async function loadTools() {
  const list = el("tools");
  try {
    const tools = await api("/tools");
    list.textContent = "";
    if (!tools.length) {
      list.append(Object.assign(document.createElement("li"), { className: "history__empty", textContent: "No tools registered." }));
      return;
    }
    tools.forEach((tool) => {
      const item = document.createElement("li");
      item.className = "history__item";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "history__button";
      button.title = tool.description || tool.name;
      const name = document.createElement("span");
      name.className = "history__prompt";
      name.textContent = tool.name;
      const meta = document.createElement("span");
      meta.className = "history__meta";
      meta.textContent = (tool.capabilities || []).join(" · ");
      button.append(name, meta);
      item.append(button);
      list.append(item);
    });
  } catch (error) {
    list.textContent = "";
    list.append(Object.assign(document.createElement("li"), { className: "history__empty", textContent: error.message }));
  }
}

async function loadHistory() {
  const list = el("history");
  try {
    const tasks = await api("/tasks");
    list.textContent = "";
    if (!tasks.length) {
      list.append(Object.assign(document.createElement("li"), { className: "history__empty", textContent: "No tasks yet — submit one to get started." }));
      return;
    }
    tasks.forEach((task) => {
      const item = document.createElement("li");
      item.className = "history__item";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "history__button";
      button.dataset.taskId = task.id;
      button.setAttribute("aria-current", String(task.id === state.activeTaskId));
      const prompt = document.createElement("span");
      prompt.className = "history__prompt";
      prompt.textContent = task.prompt;
      const meta = document.createElement("span");
      meta.className = "history__meta";
      meta.textContent = `${task.status} · ${(task.created_at || "").slice(11, 19)}`;
      button.append(prompt, meta);
      button.addEventListener("click", () => selectTask(task.id));
      item.append(button);
      list.append(item);
    });
  } catch (error) {
    list.textContent = "";
    list.append(Object.assign(document.createElement("li"), { className: "history__empty", textContent: error.message }));
  }
}

async function loadArtifacts() {
  const list = el("artifacts");
  try {
    const artifacts = await api("/artifacts");
    list.textContent = "";
    if (!artifacts.length) {
      list.append(Object.assign(document.createElement("li"), { className: "artifacts__empty", textContent: "No files yet." }));
      return;
    }
    artifacts.forEach((artifact) => {
      const item = document.createElement("li");
      item.className = "artifact";
      const link = document.createElement("a");
      link.className = "artifact__link";
      link.href = `${API}/artifacts/${artifact.path.split("/").map(encodeURIComponent).join("/")}`;
      link.target = "_blank";
      link.rel = "noopener";
      const name = document.createElement("span");
      name.className = "artifact__name";
      name.textContent = artifact.path;
      const size = document.createElement("span");
      size.className = "artifact__size";
      size.textContent = formatBytes(artifact.size_bytes);
      const when = document.createElement("span");
      when.className = "artifact__when";
      when.textContent = (artifact.modified_at || "").slice(11, 19);
      link.append(name, size, when);
      item.append(link);
      list.append(item);
    });
  } catch (error) {
    list.textContent = "";
    list.append(Object.assign(document.createElement("li"), { className: "artifacts__empty", textContent: error.message }));
  }
}

/* -- live updates --------------------------------------------------------- */

async function applyTask(task, { resetLog = false } = {}) {
  state.activeTaskId = task.id;
  setRunStatus(task.status);
  renderSteps(task.steps || []);
  if (resetLog) {
    state.cursor = 0;
    appendEvents([], { replace: true });
  }
  if (["completed", "partial", "failed"].includes(task.status)) {
    state.terminal = true;
    showError(task.error ? "TASK_FAILED" : "", task.error || "");
    renderResult(task);
    loadArtifacts();
    loadHistory();
  }
}

async function pumpEvents(taskId) {
  const page = await api(`/tasks/${taskId}/events?since=${state.cursor}`);
  if (page.events.length) {
    appendEvents(page.events);
    state.cursor = page.next_seq;
  }
  return page;
}

function closeStreams() {
  if (state.stream) {
    state.stream.close();
    state.stream = null;
  }
  if (state.poller) {
    clearInterval(state.poller);
    state.poller = null;
  }
}

function startPolling(taskId) {
  state.poller = setInterval(async () => {
    try {
      const page = await pumpEvents(taskId);
      const task = await api(`/tasks/${taskId}`);
      await applyTask(task);
      if (page.terminal && state.cursor >= page.next_seq) {
        closeStreams();
      }
    } catch (error) {
      showError("POLL_FAILED", error.message);
    }
  }, POLL_INTERVAL_MS);
}

function startStream(taskId) {
  if (!("EventSource" in window)) {
    startPolling(taskId);
    return;
  }
  const stream = new EventSource(`${API}/tasks/${taskId}/stream?since=0`);
  state.stream = stream;

  const handle = (event) => {
    try {
      const payload = JSON.parse(event.data);
      appendEvents([payload]);
      state.cursor = Math.max(state.cursor, payload.seq || 0);
    } catch {
      /* a malformed frame must not stop the stream */
    }
  };

  ["plan_start", "step_start", "step_complete", "step_failed", "recovery", "plan_complete", "task_finished"].forEach((kind) => {
    stream.addEventListener(kind, handle);
  });

  stream.addEventListener("done", async () => {
    closeStreams();
    await refreshTask(taskId);
  });

  stream.onerror = () => {
    /* Transport failure: fall back to the cursor-based poll and keep the session. */
    if (state.stream === stream) {
      stream.close();
      state.stream = null;
      if (!state.terminal) startPolling(taskId);
    }
  };
}

async function refreshTask(taskId) {
  const task = await api(`/tasks/${taskId}`);
  await applyTask(task);
  return task;
}

async function selectTask(taskId) {
  closeStreams();
  state.terminal = false;
  el("result-panel").hidden = true;
  const task = await refreshTask(taskId);
  await pumpEvents(taskId);
  await loadHistory();
  if (!["completed", "partial", "failed"].includes(task.status)) {
    startStream(taskId);
  }
}

async function submitTask(prompt) {
  showError("", "");
  const button = el("submit");
  button.disabled = true;
  button.textContent = "Submitting…";
  try {
    const task = await api("/tasks", { method: "POST", body: JSON.stringify({ prompt }) });
    el("task-prompt").setAttribute("aria-invalid", "false");
    await applyTask(task, { resetLog: true });
    await loadHistory();
    startStream(task.id);
  } catch (error) {
    el("task-prompt").setAttribute("aria-invalid", "true");
    el("prompt-error").textContent = error.message;
    showError(error.code, error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Run task";
  }
}

/* -- wiring --------------------------------------------------------------- */

el("task-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = el("task-prompt").value.trim();
  if (!prompt) {
    el("task-prompt").setAttribute("aria-invalid", "true");
    el("prompt-error").textContent = "Enter a task before running.";
    el("task-prompt").focus();
    return;
  }
  el("prompt-error").textContent = "";
  submitTask(prompt);
});

el("task-prompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    el("task-form").requestSubmit();
  }
});

document.querySelectorAll("[data-preset]").forEach((button) => {
  button.addEventListener("click", () => {
    el("task-prompt").value = button.dataset.preset;
    el("task-prompt").focus();
  });
});

document.querySelectorAll('[role="tab"]').forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll('[role="tab"]').forEach((other) => {
      const selected = other === tab;
      other.setAttribute("aria-selected", String(selected));
      el(other.getAttribute("aria-controls")).hidden = !selected;
    });
  });
});

el("refresh").addEventListener("click", () => {
  loadHealth();
  loadTools();
  loadHistory();
  loadArtifacts();
});
el("refresh-artifacts").addEventListener("click", loadArtifacts);

loadHealth();
loadTools();
loadHistory();
loadArtifacts();
setInterval(loadArtifacts, 5000);
