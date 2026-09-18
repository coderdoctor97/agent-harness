/* =============================================================================
   Agent Harness — Arena-style AI Development Environment Client
   ========================================================================== */

const API = "/api";
const POLL_INTERVAL_MS = 1000;

const STEP_STATUS_BADGE = {
  pending: "badge--idle",
  running: "badge--running",
  retrying: "badge--paused",
  success: "badge--completed",
  completed: "badge--completed",
  failed: "badge--failed",
  skipped: "badge--idle",
};

const state = {
  activeTaskId: null,
  cursor: 0,
  stream: null,
  poller: null,
  terminal: false,
  status: "idle",
  phase: "idle",
  startTime: null,
  elapsedTimer: null,
  selectedFile: null,
  currentTab: "diff",
  workspace: null,
  git: null,
};

const el = (id) => document.getElementById(id);

/* -- API Client (Relative URLs only) --------------------------------------- */

async function api(path, options = {}) {
  const url = path.startsWith("/api") ? path : `${API}${path}`;
  const response = await fetch(url, {
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    ...options,
  });

  if (response.status === 204) return null;

  let body = null;
  const text = await response.text();
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { message: text };
  }

  if (!response.ok) {
    const error = new Error((body && (body.message || body.detail)) || `HTTP ${response.status}`);
    error.status = response.status;
    error.code = (body && body.code) || "HTTP_ERROR";
    throw error;
  }
  return body;
}

/* -- Formatters ------------------------------------------------------------ */

function formatDuration(ms) {
  if (!ms) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatClock(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function badge(status) {
  const cls = STEP_STATUS_BADGE[status] || "badge--idle";
  const node = document.createElement("span");
  node.className = `badge ${cls}`;
  node.textContent = status || "pending";
  return node;
}

/* -- UI State Sync --------------------------------------------------------- */

function updateAgentStatus(status, phase = null) {
  state.status = status;
  if (phase) state.phase = phase;

  const topBadge = el("agent-status-badge");
  const topText = el("agent-status-text");
  const sessBadge = el("session-status-badge");
  const sessPhase = el("session-phase");
  const liveIndicator = el("live-indicator");
  const pauseBtn = el("agent-pause-btn");
  const stopBtn = el("agent-stop-btn");

  const normalized = (status || "idle").toLowerCase();
  topText.textContent = normalized.replace("_", " ").toUpperCase();
  sessBadge.textContent = normalized.replace("_", " ").toUpperCase();
  sessPhase.textContent = phase || (normalized === "running" ? "Executing" : normalized);

  topBadge.className = `badge badge--status badge--${normalized}`;
  sessBadge.className = `badge badge--sm badge--${normalized}`;

  const isRunning = normalized === "running";
  const isPaused = normalized === "paused";
  const isAwaiting = normalized === "awaiting_input";

  liveIndicator.hidden = !isRunning;
  pauseBtn.hidden = !(isRunning || isPaused);
  pauseBtn.textContent = isPaused ? "Resume" : "Pause";
  stopBtn.hidden = !(isRunning || isPaused || isAwaiting);

  if (isRunning) {
    if (!state.startTime) state.startTime = Date.now();
    startElapsedTimer();
  } else if (normalized === "completed" || normalized === "failed" || normalized === "stopped") {
    stopElapsedTimer();
  }
}

function startElapsedTimer() {
  if (state.elapsedTimer) return;
  state.elapsedTimer = setInterval(() => {
    if (!state.startTime) return;
    const elapsedSecs = (Date.now() - state.startTime) / 1000;
    el("session-elapsed").textContent = formatClock(elapsedSecs);
  }, 1000);
}

function stopElapsedTimer() {
  if (state.elapsedTimer) {
    clearInterval(state.elapsedTimer);
    state.elapsedTimer = null;
  }
}

function addActivity(text, type = "done") {
  const list = el("activity-list");
  const item = document.createElement("li");
  item.className = `activity-item activity-item--${type}`;

  const icon = document.createElement("span");
  icon.className = "activity-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = type === "done" ? "✓" : type === "active" ? "●" : "○";

  const span = document.createElement("span");
  span.textContent = text;

  item.append(icon, span);
  list.prepend(item);

  while (list.children.length > 8) {
    list.lastChild.remove();
  }
}

function updateRoadmap(roadmap) {
  if (!roadmap || !roadmap.length) return;
  const list = el("roadmap-list");
  list.querySelectorAll(".roadmap-item").forEach((item) => {
    const key = item.dataset.milestone;
    const match = roadmap.find((m) => m.id === key);
    if (!match) return;

    item.className = `roadmap-item roadmap-item--${match.status}`;
    const icon = item.querySelector(".roadmap-icon");
    if (icon) {
      if (match.status === "completed") icon.textContent = "✓";
      else if (match.status === "running") icon.textContent = "●";
      else if (match.status === "failed") icon.textContent = "✗";
      else icon.textContent = "○";
    }
  });
}

function renderCheckpoint(checkpoint) {
  const card = el("checkpoint-card");
  if (!checkpoint) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  el("checkpoint-phase-name").textContent = checkpoint.phase || "Checkpoint";
  el("checkpoint-message").textContent = checkpoint.message || "The agent completed this phase.";
  el("checkpoint-files-count").textContent = checkpoint.files_changed || 0;
  el("checkpoint-tests-count").textContent = checkpoint.tests_passed || 0;
  updateAgentStatus("awaiting_input", "Checkpoint");
}

/* -- Workspace & Git Sync -------------------------------------------------- */

async function loadStatus() {
  try {
    const data = await api("/status");
    if (!data) return;

    state.workspace = data.workspace;
    state.git = data.git;

    if (data.workspace) {
      el("topbar-workspace-name").textContent = data.workspace.name || "workspace";
      const isGithub = data.workspace.connection_state === "github_connected";
      el("connection-label").textContent = isGithub ? "● GitHub Connected" : "● Local Sandbox";
      el("git-status-badge").textContent = isGithub ? "GITHUB" : "LOCAL";
    }

    if (data.git) {
      const branch = data.git.branch || "main";
      el("topbar-branch").textContent = branch;
      el("git-branch-val").textContent = branch;
      el("git-repo-val").textContent = data.workspace ? data.workspace.name : "-";
      el("git-diff-summary").textContent = `${data.git.modified_count || 0} modified`;
    }

    if (data.agent_state && data.agent_state !== "idle" && data.active_task_id) {
      if (state.activeTaskId !== data.active_task_id) {
        selectTask(data.active_task_id);
      }
    }
  } catch {
    /* Background health probe */
  }
}

async function loadHealth() {
  try {
    const data = await api("/health");
    if (!data) return;
    el("health-provider").textContent = data.provider || "openai";
    el("health-model").textContent = data.model || "gpt-4o";
    el("health-output").textContent = data.output_dir || "./output";
    el("health-key").textContent = data.api_key_configured ? "Configured (Hidden)" : "Missing";
  } catch {
    /* Silent */
  }
}

/* -- Workspace File Explorer ----------------------------------------------- */

async function loadFiles() {
  try {
    const data = await api("/files");
    const container = el("file-tree-view");
    container.textContent = "";

    if (!data.tree || !data.tree.length) {
      container.textContent = "No files in workspace root.";
      return;
    }

    renderTreeNodes(data.tree, container, 0);
  } catch (err) {
    el("file-tree-view").textContent = `Error loading files: ${err.message}`;
  }
}

function renderTreeNodes(nodes, container, depth) {
  nodes.forEach((node) => {
    const row = document.createElement("div");
    row.className = `tree-node ${node.modified ? "tree-node--modified" : ""}`;
    row.style.paddingLeft = `${depth * 14 + 8}px`;

    const left = document.createElement("span");
    left.textContent = `${node.type === "directory" ? "📁 " : "📄 "}${node.name}`;

    const right = document.createElement("span");
    if (node.modified) {
      right.textContent = "M";
      right.style.color = "var(--status-warn)";
    } else if (node.type === "file" && node.size) {
      right.textContent = formatBytes(node.size);
      right.style.color = "var(--ink-muted)";
    }

    row.append(left, right);
    container.append(row);

    if (node.type === "file") {
      row.addEventListener("click", () => selectFile(node.path));
    } else if (node.children && node.children.length) {
      const childWrap = document.createElement("div");
      childWrap.className = "tree-children";
      renderTreeNodes(node.children, childWrap, depth + 1);
      container.append(childWrap);

      row.addEventListener("click", () => {
        childWrap.hidden = !childWrap.hidden;
        left.textContent = `${childWrap.hidden ? "📁 " : "📂 "}${node.name}`;
      });
    }
  });
}

async function selectFile(path) {
  state.selectedFile = path;
  el("file-preview-name").textContent = path;
  el("open-in-editor-btn").disabled = false;

  try {
    const data = await api(`/files/${encodeURIComponent(path)}`);
    el("file-preview-text").textContent = data.content;
    state.fileContent = data.content;
  } catch (err) {
    el("file-preview-text").textContent = `Could not read file: ${err.message}`;
  }
}

function openInEditor(path, content) {
  switchTab("code");
  el("editor-active-filename").textContent = path;
  el("editor-modified-badge").hidden = true;
  el("editor-save-btn").disabled = false;
  el("editor-revert-btn").disabled = false;

  const textarea = el("code-editor-textarea");
  textarea.value = content || "";
  updateLineNumbers();
}

function updateLineNumbers() {
  const textarea = el("code-editor-textarea");
  const count = (textarea.value.match(/\n/g) || []).length + 1;
  const numbers = Array.from({ length: count }, (_, i) => i + 1).join("\n");
  el("editor-line-numbers").textContent = numbers;
}

/* -- Diff Viewer ----------------------------------------------------------- */

async function loadDiff() {
  try {
    const data = await api("/diff");
    renderDiff(data);
  } catch (err) {
    el("diff-container").textContent = `Error loading diff: ${err.message}`;
  }
}

function renderDiff(diffData) {
  const container = el("diff-container");
  container.textContent = "";

  const summary = diffData.summary;
  el("diff-summary-text").textContent = summary.description || `${summary.files_changed} files changed`;
  el("diff-tab-badge").textContent = summary.files_changed || 0;

  if (!diffData.files || !diffData.files.length) {
    const empty = document.createElement("div");
    empty.className = "diff-empty";
    empty.textContent = "Working tree clean. No uncommitted modifications.";
    container.append(empty);
    return;
  }

  diffData.files.forEach((file) => {
    const card = document.createElement("div");
    card.className = "diff-file-card";

    const head = document.createElement("div");
    head.className = "diff-file-header";

    const pathSpan = document.createElement("span");
    pathSpan.textContent = `${file.status === "added" ? "✚ " : file.status === "deleted" ? "✖ " : "● "}${file.path}`;

    const counts = document.createElement("div");
    counts.className = "diff-counts";

    const addSpan = document.createElement("span");
    addSpan.className = "diff-add-count";
    addSpan.textContent = `+${file.insertions || 0}`;

    const delSpan = document.createElement("span");
    delSpan.className = "diff-del-count";
    delSpan.textContent = `-${file.deletions || 0}`;

    counts.append(addSpan, delSpan);
    head.append(pathSpan, counts);
    card.append(head);

    const linesContainer = document.createElement("div");
    linesContainer.className = "diff-lines";

    if (file.chunks && file.chunks.length) {
      file.chunks.forEach((chunk) => {
        const chunkHead = document.createElement("div");
        chunkHead.className = "diff-line diff-line--header";
        chunkHead.textContent = chunk.header;
        linesContainer.append(chunkHead);

        chunk.lines.forEach((l) => {
          const lineRow = document.createElement("div");
          lineRow.className = `diff-line diff-line--${l.type}`;
          const prefix = l.type === "add" ? "+" : l.type === "delete" ? "-" : " ";
          lineRow.textContent = `${prefix} ${l.content}`;
          linesContainer.append(lineRow);
        });
      });
    } else if (file.raw) {
      const rawLines = file.raw.split("\n");
      rawLines.forEach((l) => {
        const lineRow = document.createElement("div");
        const type = l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "delete" : "context";
        lineRow.className = `diff-line diff-line--${type}`;
        lineRow.textContent = l;
        linesContainer.append(lineRow);
      });
    }

    card.append(linesContainer);
    container.append(card);
  });
}

/* -- Terminal Runner ------------------------------------------------------- */

async function runTerminal(cmd) {
  const screen = el("terminal-screen");

  const cmdLine = document.createElement("div");
  cmdLine.className = "terminal-line terminal-line--cmd";
  cmdLine.textContent = `$ ${cmd}`;
  screen.append(cmdLine);

  try {
    const res = await api("/terminal/run", {
      method: "POST",
      body: JSON.stringify({ command: cmd }),
    });

    if (res.stdout) {
      const outLine = document.createElement("div");
      outLine.className = "terminal-line terminal-line--stdout";
      outLine.textContent = res.stdout;
      screen.append(outLine);
    }
    if (res.stderr) {
      const errLine = document.createElement("div");
      errLine.className = "terminal-line terminal-line--stderr";
      errLine.textContent = res.stderr;
      screen.append(errLine);
    }

    const infoLine = document.createElement("div");
    infoLine.className = "terminal-line terminal-line--info";
    infoLine.textContent = `[Process finished with exit code ${res.exit_code} in ${formatDuration(res.duration_ms)}]`;
    screen.append(infoLine);
  } catch (err) {
    const failLine = document.createElement("div");
    failLine.className = "terminal-line terminal-line--stderr";
    failLine.textContent = `Execution failed: ${err.message}`;
    screen.append(failLine);
  }

  screen.scrollTop = screen.scrollHeight;
}

/* -- PR Automation Modal --------------------------------------------------- */

async function openPRModal() {
  const modal = el("pr-modal");
  try {
    const pr = await api("/pr/prepare", { method: "POST" });
    el("pr-title-input").value = pr.title || "";
    el("pr-desc-textarea").value = pr.description || "";

    const notice = el("pr-status-notice");
    if (!pr.is_github) {
      notice.textContent = "Connect GitHub to create a Pull Request. Local diff review remains fully functional.";
      el("pr-create-btn").disabled = true;
    } else {
      notice.textContent = `Ready to open PR on branch: ${pr.branch}`;
      el("pr-create-btn").disabled = false;
    }

    modal.showModal();
  } catch (err) {
    alert(`Could not prepare PR: ${err.message}`);
  }
}

async function submitPR() {
  const title = el("pr-title-input").value.trim();
  const desc = el("pr-desc-textarea").value.trim();
  if (!title) return alert("Title is required.");

  try {
    const res = await api("/pr/create", {
      method: "POST",
      body: JSON.stringify({ title, description: desc }),
    });
    if (res.success) {
      alert(`Pull Request Created: ${res.url}`);
      el("pr-modal").close();
    } else {
      alert(`PR creation notice: ${res.error || res.message}`);
    }
  } catch (err) {
    alert(`Failed to create PR: ${err.message}`);
  }
}

/* -- Task Execution & Streaming -------------------------------------------- */

function renderSteps(steps) {
  const list = el("steps");
  list.textContent = "";
  if (!steps || !steps.length) {
    const empty = document.createElement("li");
    empty.className = "artifacts__empty";
    empty.textContent = "Waiting for plan decomposition…";
    list.append(empty);
    return;
  }

  steps.forEach((step, index) => {
    const card = document.createElement("li");
    card.className = "step-card";

    const left = document.createElement("div");
    left.className = "step-left";

    const idSpan = document.createElement("span");
    idSpan.className = "step-id";
    idSpan.textContent = `[${step.id || index + 1}] `;

    const descSpan = document.createElement("span");
    descSpan.textContent = step.description;

    const meta = document.createElement("div");
    meta.className = "step-meta";
    if (step.tool) {
      const toolSpan = document.createElement("span");
      toolSpan.className = "step-tool";
      toolSpan.textContent = `tool: ${step.tool} `;
      meta.append(toolSpan);
    }
    if (step.duration_ms) {
      meta.append(document.createTextNode(`(${formatDuration(step.duration_ms)})`));
    }

    left.append(idSpan, descSpan, meta);
    card.append(left, badge(step.status));
    list.append(card);
  });
}

function appendLogEvent(evt) {
  const log = el("log");
  const empty = log.querySelector(".log__empty");
  if (empty) empty.remove();

  const entry = document.createElement("div");
  entry.className = "log-entry";

  const timeSpan = document.createElement("span");
  timeSpan.className = "log-time";
  timeSpan.textContent = evt.at ? evt.at.slice(11, 19) : "";

  const kindSpan = document.createElement("span");
  kindSpan.className = "log-event";
  kindSpan.textContent = `[${evt.event}]`;

  const descSpan = document.createElement("span");
  const fields = evt.fields || {};
  let text = "";
  if (evt.event === "step_start") text = `Starting step ${fields.step_id || ""}: ${fields.description || fields.tool || ""}`;
  else if (evt.event === "step_complete") text = `Completed step ${fields.step_id || ""}`;
  else if (evt.event === "step_failed") text = `Failed step ${fields.step_id || ""}: ${fields.error || ""}`;
  else if (evt.event === "user_intervention") text = `User Instruction: "${fields.instruction || ""}"`;
  else if (evt.event === "agent_paused") text = "Agent execution paused by user.";
  else if (evt.event === "agent_resumed") text = "Agent execution resumed.";
  else if (evt.event === "checkpoint_created") text = `Checkpoint reached for phase: ${fields.phase || ""}`;
  else text = JSON.stringify(fields);

  descSpan.textContent = text;
  entry.append(timeSpan, kindSpan, descSpan);
  log.append(entry);
  log.scrollTop = log.scrollHeight;
}

function applyTask(task, options = {}) {
  state.activeTaskId = task.id;
  state.terminal = ["completed", "partial", "failed", "stopped"].includes(task.status);

  el("session-task-text").textContent = task.prompt;
  updateAgentStatus(task.status, task.phase);
  updateRoadmap(task.roadmap);
  renderCheckpoint(task.checkpoint);
  renderSteps(task.steps);

  if (task.active_tool) {
    el("active-tools-container").hidden = false;
    el("active-tool-tag").textContent = task.active_tool;
  } else {
    el("active-tools-container").hidden = true;
  }

  if (task.final_output) {
    el("output").textContent = "";
    const pre = document.createElement("pre");
    pre.className = "output__prose";
    pre.textContent = task.final_output;
    el("output").append(pre);
  }

  if (task.report) {
    const reportPre = el("report").querySelector("pre");
    if (reportPre) reportPre.textContent = task.report;
  }

  if (options.resetLog) {
    const log = el("log");
    log.textContent = "";
    state.cursor = 0;
  }
}

async function pumpEvents(taskId) {
  try {
    const page = await api(`/tasks/${taskId}/events?since=${state.cursor}`);
    if (page) {
      if (typeof page.next_seq === "number") {
        state.cursor = page.next_seq;
      }
      if (page.events && page.events.length) {
        page.events.forEach((evt) => {
          appendLogEvent(evt);
          state.cursor = Math.max(state.cursor, evt.seq || 0);
          if (evt.event === "step_start" && evt.fields && evt.fields.tool) {
            addActivity(`Modifying / Running: ${evt.fields.tool}`, "active");
          } else if (evt.event === "step_complete") {
            addActivity(`Step complete: ${evt.fields.step_id || ""}`, "done");
          }
        });
      }
    }
  } catch {
    /* Silent */
  }
}

function startPolling(taskId) {
  stopPolling();
  state.poller = setInterval(async () => {
    await pumpEvents(taskId);
    const task = await api(`/tasks/${taskId}`);
    applyTask(task);
    if (state.terminal) stopPolling();
  }, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (state.poller) {
    clearInterval(state.poller);
    state.poller = null;
  }
}

function closeStreams() {
  if (state.stream) {
    state.stream.close();
    state.stream = null;
  }
  stopPolling();
}

function startStream(taskId) {
  closeStreams();
  const url = `${API}/tasks/${taskId}/stream?since=${state.cursor}`;
  const stream = new EventSource(url);
  state.stream = stream;

  const handle = (event) => {
    try {
      const payload = JSON.parse(event.data);
      appendLogEvent(payload);
      state.cursor = Math.max(state.cursor, payload.seq || 0);
      if (payload.event === "step_start") {
        addActivity(`Step: ${payload.fields.tool || payload.fields.step_id || ""}`, "active");
      }
    } catch {
      /* Frame parsing */
    }
  };

  [
    "plan_start", "step_start", "step_complete", "step_failed", "recovery",
    "plan_complete", "task_finished", "agent_paused", "agent_resumed",
    "checkpoint_created", "checkpoint_resolved", "user_intervention",
  ].forEach((kind) => {
    stream.addEventListener(kind, handle);
  });

  stream.addEventListener("done", async () => {
    closeStreams();
    const task = await api(`/tasks/${taskId}`);
    applyTask(task);
    await loadDiff();
  });

  stream.onerror = () => {
    if (state.stream === stream) {
      stream.close();
      state.stream = null;
      if (!state.terminal) startPolling(taskId);
    }
  };
}

async function selectTask(taskId) {
  closeStreams();
  state.terminal = false;
  state.cursor = 0;
  const task = await api(`/tasks/${taskId}`);
  applyTask(task, { resetLog: true });
  await pumpEvents(taskId);
  if (!state.terminal) {
    startStream(taskId);
  }
}

async function loadHistory() {
  try {
    const list = await api("/tasks?limit=10");
    const container = el("history");
    container.textContent = "";

    if (!list || !list.length) {
      const empty = document.createElement("li");
      empty.className = "history__empty";
      empty.textContent = "No tasks yet.";
      container.append(empty);
      return;
    }

    list.forEach((t) => {
      const li = document.createElement("li");
      li.className = "history-item";
      li.textContent = `${t.status === "completed" ? "✓" : "●"} ${t.prompt}`;
      li.addEventListener("click", () => selectTask(t.id));
      container.append(li);
    });
  } catch {
    /* History silent */
  }
}

async function loadArtifacts() {
  try {
    const items = await api("/artifacts");
    const container = el("artifacts");
    container.textContent = "";

    if (!items || !items.length) {
      const empty = document.createElement("li");
      empty.className = "artifacts__empty";
      empty.textContent = "No artifacts in output directory.";
      container.append(empty);
      return;
    }

    items.forEach((item) => {
      const li = document.createElement("li");
      li.className = "artifact-item";

      const link = document.createElement("a");
      link.href = `/api/artifacts/${encodeURIComponent(item.path)}`;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = item.name;

      const sizeSpan = document.createElement("span");
      sizeSpan.textContent = formatBytes(item.size_bytes);

      li.append(link, sizeSpan);
      container.append(li);
    });
  } catch {
    /* Silent */
  }
}

/* -- Interactive Agent Commands -------------------------------------------- */

async function handlePauseClick() {
  if (state.status === "paused") {
    const task = await api("/agent/resume", {
      method: "POST",
      body: JSON.stringify({ task_id: state.activeTaskId }),
    });
    applyTask(task);
  } else {
    const task = await api("/agent/pause", {
      method: "POST",
      body: JSON.stringify({ task_id: state.activeTaskId }),
    });
    applyTask(task);
  }
}

async function handleStopClick() {
  if (!confirm("Are you sure you want to stop the current agent task?")) return;
  const task = await api("/agent/stop", {
    method: "POST",
    body: JSON.stringify({ task_id: state.activeTaskId }),
  });
  applyTask(task);
  closeStreams();
}

async function handleApproveCheckpoint() {
  const task = await api("/agent/approve", {
    method: "POST",
    body: JSON.stringify({ task_id: state.activeTaskId }),
  });
  applyTask(task);
  await loadDiff();
}

async function handleRejectCheckpoint() {
  const reason = prompt("Enter feedback or rejection reason for the agent:");
  if (reason === null) return;
  const task = await api("/agent/reject", {
    method: "POST",
    body: JSON.stringify({ task_id: state.activeTaskId, reason }),
  });
  applyTask(task);
  closeStreams();
}

/* -- Tab Switching --------------------------------------------------------- */

function switchTab(tabName) {
  state.currentTab = tabName;
  document.querySelectorAll('[role="tablist"] > .tab').forEach((tab) => {
    const isTarget = tab.id === `tab-${tabName}`;
    tab.setAttribute("aria-selected", String(isTarget));
    const panelId = tab.getAttribute("aria-controls");
    const panel = el(panelId);
    if (panel) panel.hidden = !isTarget;
  });

  if (tabName === "files") loadFiles();
  else if (tabName === "diff") loadDiff();
  else if (tabName === "artifacts") loadArtifacts();
}

/* -- Task Submission & Slash Commands -------------------------------------- */

async function submitTask(prompt) {
  const trimmed = prompt.trim();
  if (!trimmed) return;

  // Slash command processing
  if (trimmed.startsWith("/")) {
    handleSlashCommand(trimmed);
    return;
  }

  el("prompt-error").textContent = "";
  const sendBtn = el("submit");
  sendBtn.disabled = true;

  try {
    const task = await api("/tasks", {
      method: "POST",
      body: JSON.stringify({ prompt: trimmed }),
    });
    el("task-prompt").value = "";
    state.startTime = Date.now();
    applyTask(task, { resetLog: true });
    await loadHistory();
    startStream(task.id);
  } catch (err) {
    el("prompt-error").textContent = err.message;
  } finally {
    sendBtn.disabled = false;
  }
}

function handleSlashCommand(cmd) {
  const [token, ...rest] = cmd.split(" ");
  const sub = rest.join(" ");

  if (token === "/plan") {
    switchTab("steps");
    runTerminal(`python -m agent_harness --dry-run "${sub || 'Task plan'}"`);
  } else if (token === "/test") {
    switchTab("terminal");
    runTerminal(sub ? `pytest ${sub}` : "pytest");
  } else if (token === "/diff") {
    switchTab("diff");
    loadDiff();
  } else if (token === "/review") {
    switchTab("diff");
    loadDiff();
  } else if (token === "/status") {
    loadStatus();
    loadHealth();
    el("settings-modal").showModal();
  } else if (token === "/help") {
    alert("Available slash commands:\n/plan <task> - Generate step plan\n/test - Run pytest suite\n/diff - Inspect workspace diff\n/review - Review changes\n/status - System status\n/help - Command summary");
  }
}

/* -- Event Listeners & Wiring ---------------------------------------------- */

el("task-form").addEventListener("submit", (e) => {
  e.preventDefault();
  submitTask(el("task-prompt").value);
});

el("task-prompt").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    el("task-form").requestSubmit();
  }
});

// Slash command pills
document.querySelectorAll(".pill-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const cmd = btn.dataset.cmd;
    const input = el("task-prompt");
    input.value = cmd;
    input.focus();
  });
});

// Workspace tab switching
document.querySelectorAll('.tabs > .tab').forEach((tab) => {
  tab.addEventListener("click", () => {
    const tabName = tab.id.replace("tab-", "");
    switchTab(tabName);
  });
});

// Deliverable subtabs
document.querySelectorAll(".subtab").forEach((subtab) => {
  subtab.addEventListener("click", () => {
    document.querySelectorAll(".subtab").forEach((s) => {
      const active = s === subtab;
      s.classList.toggle("subtab--active", active);
      s.setAttribute("aria-selected", String(active));
      const panel = el(s.getAttribute("aria-controls"));
      if (panel) panel.hidden = !active;
    });
  });
});

// Sidebar toggle
el("sidebar-toggle").addEventListener("click", () => {
  el("sidebar").classList.toggle("sidebar--collapsed");
});

// Settings Modal
el("settings-btn").addEventListener("click", () => {
  loadHealth();
  el("settings-modal").showModal();
});
el("settings-close-btn").addEventListener("click", () => el("settings-modal").close());
el("refresh").addEventListener("click", () => {
  loadHealth();
  loadStatus();
});

// PR Automation
el("open-pr-panel-btn").addEventListener("click", openPRModal);
el("pr-close-btn").addEventListener("click", () => el("pr-modal").close());
el("pr-create-btn").addEventListener("click", submitPR);
el("pr-review-diff-btn").addEventListener("click", () => {
  el("pr-modal").close();
  switchTab("diff");
});

// Checkpoint actions
el("checkpoint-approve-btn").addEventListener("click", handleApproveCheckpoint);
el("checkpoint-reject-btn").addEventListener("click", handleRejectCheckpoint);
el("checkpoint-review-btn").addEventListener("click", () => switchTab("diff"));

// Agent pause / stop controls
el("agent-pause-btn").addEventListener("click", handlePauseClick);
el("agent-stop-btn").addEventListener("click", handleStopClick);

// File explorer actions
el("open-in-editor-btn").addEventListener("click", () => {
  if (state.selectedFile) openInEditor(state.selectedFile, state.fileContent);
});

el("editor-save-btn").addEventListener("click", async () => {
  if (!state.selectedFile) return;
  const content = el("code-editor-textarea").value;
  try {
    await api("/files/save", {
      method: "POST",
      body: JSON.stringify({ path: state.selectedFile, content }),
    });
    alert(`File saved: ${state.selectedFile}`);
    await loadDiff();
  } catch (err) {
    alert(`Failed to save file: ${err.message}`);
  }
});

el("editor-revert-btn").addEventListener("click", () => {
  if (state.fileContent) el("code-editor-textarea").value = state.fileContent;
});

el("code-editor-textarea").addEventListener("input", updateLineNumbers);

// Diff tab refresh
el("diff-refresh-btn").addEventListener("click", loadDiff);
el("refresh-tab-btn").addEventListener("click", () => switchTab(state.currentTab));

// Terminal actions
el("term-run-pytest").addEventListener("click", () => runTerminal("pytest tests/test_web"));
el("term-run-ruff").addEventListener("click", () => runTerminal("ruff check agent_harness/web"));
el("term-run-git-status").addEventListener("click", () => runTerminal("git status"));
el("term-clear").addEventListener("click", () => { el("terminal-screen").textContent = ""; });
el("terminal-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = el("terminal-custom-command");
  if (input.value.trim()) {
    runTerminal(input.value.trim());
    input.value = "";
  }
});

// Attachment prompt helper
el("prompt-attach-btn").addEventListener("click", () => {
  const path = prompt("Enter relative file path to attach (e.g. pyproject.toml):");
  if (path) {
    el("task-prompt").value += ` @${path} `;
    el("task-prompt").focus();
  }
});

// Preset buttons (compatibility)
document.querySelectorAll("[data-preset]").forEach((btn) => {
  btn.addEventListener("click", () => {
    el("task-prompt").value = btn.dataset.preset;
    el("task-prompt").focus();
  });
});

// Initial boot
loadStatus();
loadHealth();
loadHistory();
loadDiff();
loadFiles();
loadArtifacts();
setInterval(loadStatus, 4000);
