# Agent Harness: General-Purpose Autonomous Agent Execution

## Complete PRD & Developer README

---

# PART 1: PRODUCT REQUIREMENTS DOCUMENT (PRD)

---

## 1. Executive Summary

Agent Harness is a local-first, general-purpose autonomous agent execution framework inspired by Arena.ai's Agent Mode architecture. It accepts a single natural-language prompt and autonomously decomposes it into a multi-step execution plan, selects and invokes appropriate tools (web search, code execution, file I/O, data transformation), handles failures with automatic retry/fallback, and delivers a final assembled output — all with full transparency and extensibility. This PRD defines the system's purpose, architecture, behavior contracts, tool interfaces, orchestration model, failure-recovery semantics, and success criteria. The companion Developer README (Part 2) provides concrete implementation guidance.

---

## 2. Problem Statement

### The Gap

Modern LLMs are powerful reasoning engines, but they remain stateless, single-turn text generators without built-in agency. Turning an LLM into an *agent* — something that can plan, act, observe, and adapt across multiple steps — requires significant orchestration infrastructure:

- **Task decomposition** — breaking a complex prompt into ordered sub-tasks.
- **Tool selection and dispatch** — choosing the right capability (search, code, file ops) for each sub-task.
- **State management** — carrying context, intermediate results, and error states across steps.
- **Failure recovery** — detecting when a step fails and autonomously selecting an alternative strategy.
- **Output assembly** — combining sub-task results into a coherent final deliverable.

Existing solutions (LangChain, AutoGPT, CrewAI) either impose heavy abstractions, require cloud infrastructure, or lack robust failure-recovery semantics. Arena.ai's Agent Mode demonstrated that a lean, local-first harness with a well-defined tool interface and a plan-execute-observe loop can achieve production-grade agentic behavior without these tradeoffs.

### Who This Serves

| Persona | Need |
|---|---|
| **Student/Researcher** | Automate multi-step research workflows (search → extract → synthesize → report) from a single prompt |
| **Developer** | Scaffold projects, generate boilerplate, run code, process data files autonomously |
| **Startup Operator** | Prototype internal automation (lead research, competitive analysis, report generation) without DevOps overhead |
| **AI/ML Practitioner** | Experiment with agentic architectures, custom tools, and orchestration strategies locally |

---

## 3. Goals & Non-Goals

### Goals

| ID | Goal | Priority |
|---|---|---|
| G1 | Accept a single natural-language prompt and produce a complete, multi-step execution plan | **P0** |
| G2 | Execute plans using a pluggable tool system (web search, code execution, file I/O, data transformation) | **P0** |
| G3 | Automatically detect step failures and recover via retry, fallback tools, or re-planning | **P0** |
| G4 | Maintain full execution transparency (structured logs, step-by-step status, intermediate outputs) | **P0** |
| G5 | Provide an extensible plugin/tool registration interface for custom capabilities | **P1** |
| G6 | Run entirely locally with no cloud infrastructure dependencies beyond the LLM API | **P1** |
| G7 | Support multiple LLM backends (OpenAI, Anthropic, local models via OpenAI-compatible APIs) | **P1** |
| G8 | Provide a minimal CLI interface and optional lightweight web UI | **P2** |

### Non-Goals

| ID | Non-Goal | Rationale |
|---|---|---|
| NG1 | Production SaaS deployment | This is a local-first prototyping/research tool |
| NG2 | User authentication, multi-tenancy, or access control | Single-user, local execution model |
| NG3 | Persistent cloud infrastructure or managed hosting | Runs on user's machine |
| NG4 | Real-time streaming collaboration | Single-operator, single-session design |
| NG5 | Replacing full-featured platforms (LangChain, AutoGPT) | Focused on lean, transparent, extensible core |

---

## 4. Architecture Overview

### 4.1 Core Loop: Plan → Execute → Observe → Adapt

The Agent Harness follows a **POEA (Plan-Orchestrate-Execute-Adapt)** loop, directly inspired by Arena.ai's agent execution model:

```text
┌─────────────────────────────────────────────────────────┐
│ USER PROMPT                                             │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│ PLANNER (LLM)                                           │
│ - Decomposes prompt into ordered sub-tasks              │
│ - Assigns tool hints per sub-task                       │
│ - Produces structured ExecutionPlan                     │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│ ORCHESTRATOR                                             │
│ - Iterates through ExecutionPlan steps                  │
│ - Selects tool for each step                            │
│ - Manages context/state between steps                   │
│ - Handles dependencies between sub-tasks                │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │ STEP EXECUTION                                   │   │
│  │                                                  │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐         │   │
│  │  │ Tool A   │ │ Tool B   │ │ Tool C   │         │   │
│  │  │ (Search) │ │ (Code)   │ │ (File)   │         │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘         │   │
│  │       │            │            │                │   │
│  │       ▼            ▼            ▼                │   │
│  │  ┌──────────────────────────────────────────┐    │   │
│  │  │ STEP RESULT                              │    │   │
│  │  │ - success/failure status                 │    │   │
│  │  │ - output data                            │    │   │
│  │  │ - error details (if failed)              │    │   │
│  │  └──────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │ OBSERVER / ADAPTER                               │   │
│  │ - Evaluates step result                          │   │
│  │ - On failure: retry → fallback tool → re-plan   │   │
│  │ - On success: feed result to next step context  │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│ ASSEMBLER                                               │
│ - Combines all step outputs                             │
│ - Formats final deliverable per prompt instructions     │
│ - Writes output files / displays results                │
└─────────────────────────────────────────────────────────┘
```

### 4.2 Component Responsibilities

| Component | Responsibility | Implementation |
|---|---|---|
| **Planner** | Decomposes user prompt into structured `ExecutionPlan` with ordered `Step` objects | LLM call with structured output (JSON schema) |
| **Orchestrator** | Iterates steps, manages state, resolves dependencies, delegates to tools | Core Python class, event-driven step loop |
| **Tool Registry** | Maintains available tools, handles tool lookup by name/capability | Dictionary-based registry with interface enforcement |
| **Tool Interface** | Defines the contract all tools must implement | Abstract base class (`BaseTool`) |
| **Observer/Adapter** | Evaluates step results, triggers retry/fallback/re-plan on failure | Rule-based + optional LLM-assisted recovery |
| **Assembler** | Combines step outputs into final deliverable | Template-based or LLM-assisted synthesis |
| **Context Store** | Carries state (intermediate results, variables, file paths) across steps | In-memory dictionary with serialization support |
| **Logger** | Records all actions, decisions, errors, and timings | Structured JSON logging to file + console |

---

## 5. Data Model

### 5.1 Core Types

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import uuid
from datetime import datetime

class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"

class TaskPriority(Enum):
    CRITICAL = "critical"  # Failure blocks entire plan
    HIGH = "high"          # Failure triggers fallback
    MEDIUM = "medium"      # Failure logged, plan continues
    LOW = "low"            # Best-effort, skip on failure

@dataclass
class Step:
    """A single unit of work within an execution plan."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    tool_hint: str = ""  # Suggested tool name
    tool_name: str = ""  # Resolved tool name
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: Any = None
    status: StepStatus = StepStatus.PENDING
    error: Optional[str] = None
    retries: int = 0
    max_retries: int = 2
    fallback_tools: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)  # Step IDs
    priority: TaskPriority = TaskPriority.HIGH
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

@dataclass
class ExecutionPlan:
    """The full plan generated from a user prompt."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    original_prompt: str = ""
    steps: list[Step] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    status: StepStatus = StepStatus.PENDING
    final_output: Any = None

@dataclass
class ToolResult:
    """Standardized result from any tool execution."""
    success: bool
    output: Any = None
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 5.2 Execution Plan JSON Schema (LLM Output)

The Planner instructs the LLM to produce a structured plan:

```json
{
  "steps": [
    {
      "description": "Search for recent GPT-4 usage statistics and benchmarks",
      "tool_hint": "web_search",
      "input_data": {
        "query": "GPT-4 usage statistics 2024 benchmarks"
      },
      "priority": "high",
      "depends_on": [],
      "fallback_tools": ["web_scrape", "cached_search"]
    },
    {
      "description": "Extract key data points from search results",
      "tool_hint": "llm_extract",
      "input_data": {
        "extraction_schema": "statistics, dates, sources"
      },
      "priority": "high",
      "depends_on": ["step_0"]
    },
    {
      "description": "Generate comparison table as markdown",
      "tool_hint": "code_execute",
      "input_data": {
        "language": "python",
        "task": "Create markdown comparison table from extracted data"
      },
      "priority": "medium",
      "depends_on": ["step_1"]
    },
    {
      "description": "Write one-page summary and export as PDF",
      "tool_hint": "file_write",
      "input_data": {
        "format": "pdf",
        "filename": "gpt4_summary.pdf"
      },
      "priority": "critical",
      "depends_on": ["step_1", "step_2"]
    }
  ]
}
```

---

## 6. Tool System

### 6.1 Tool Interface Contract

Every tool must implement the `BaseTool` abstract class:

```python
from abc import ABC, abstractmethod

class BaseTool(ABC):
    """Base interface for all agent tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for LLM tool selection."""
        ...

    @property
    def capabilities(self) -> list[str]:
        """Tags describing what this tool can do."""
        return []

    @abstractmethod
    def execute(self, input_data: dict, context: dict) -> ToolResult:
        """
        Execute the tool with given input and shared context.

        Args:
            input_data: Step-specific input parameters
            context: Shared execution context (intermediate results, config)

        Returns:
            ToolResult with success/failure status, output, and metadata
        """
        ...

    def validate_input(self, input_data: dict) -> tuple[bool, str]:
        """Optional input validation. Returns (is_valid, error_message)."""
        return True, ""

    def cleanup(self) -> None:
        """Optional cleanup after execution."""
        pass
```

### 6.2 Built-in Tools

| Tool Name | Description | Input | Output | Fallback |
|---|---|---|---|---|
| `web_search` | Searches the web via SerpAPI/Bing/DuckDuckGo | `query`, `num_results` | List of `{title, url, snippet}` | `cached_search`, `web_scrape` |
| `web_scrape` | Fetches and extracts text from a URL | `url`, `selector` (optional) | Extracted text content | `web_search` with refined query |
| `code_execute` | Runs Python code in a sandboxed subprocess | `code` or `task` (LLM generates code) | stdout, stderr, return value | Re-generate code with error context |
| `file_read` | Reads local files (TXT, CSV, JSON, PDF) | `path`, `format` | File contents (text or structured) | Error with path suggestion |
| `file_write` | Writes content to local files | `path`, `content`, `format` | File path confirmation | Alternative format |
| `llm_extract` | Uses LLM to extract/transform/summarize data | `input_text`, `instruction` | Extracted/transformed text | Retry with simplified instruction |
| `llm_synthesize` | Uses LLM to generate new content from context | `instruction`, `sources` | Generated text | Retry with reduced scope |
| `pdf_export` | Converts markdown/HTML to PDF | `content`, `filename` | PDF file path | Fallback to markdown file |
| `csv_process` | Reads, filters, transforms CSV data | `path`, `operations` | Processed data | `code_execute` with pandas |
| `shell_command` | Runs a whitelisted shell command | `command`, `args` | stdout, stderr | `code_execute` equivalent |

### 6.3 Tool Registry

```python
class ToolRegistry:
    """Registry for tool discovery, registration, and lookup."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        if not isinstance(tool, BaseTool):
            raise TypeError(f"Tool must implement BaseTool interface")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def find_by_capability(self, capability: str) -> list[BaseTool]:
        """Find all tools that declare a given capability tag."""
        return [t for t in self._tools.values() if capability in t.capabilities]

    def list_tools(self) -> list[dict]:
        """List all registered tools with their descriptions (for LLM context)."""
        return [
            {"name": t.name, "description": t.description, "capabilities": t.capabilities}
            for t in self._tools.values()
        ]

    def deregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        self._tools.pop(name, None)
```

### 6.4 Custom Tool Registration

Users extend the harness by implementing `BaseTool` and registering:

```python
# my_custom_tool.py
from agent_harness.tools.base import BaseTool, ToolResult

class SlackNotifierTool(BaseTool):
    name = "slack_notify"
    description = "Sends a message to a Slack channel via webhook"
    capabilities = ["notification", "messaging"]

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def execute(self, input_data: dict, context: dict) -> ToolResult:
        import requests
        try:
            resp = requests.post(self.webhook_url, json={"text": input_data["message"]})
            resp.raise_for_status()
            return ToolResult(success=True, output="Message sent")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

# Registration (in config or startup):
# registry.register(SlackNotifierTool(webhook_url="https://hooks.slack.com/..."))
```

---

## 7. Orchestration Engine

### 7.1 Orchestrator Behavior

The Orchestrator is the core runtime loop. Its behavior contract:

```text
FOR each step in execution_plan.steps (respecting dependency order):
1. RESOLVE dependencies — ensure all depends_on steps are complete
2. RESOLVE tool — match tool_hint to registry; if not found, ask LLM to select
3. VALIDATE input — call tool.validate_input()
4. EXECUTE tool — call tool.execute(input_data, context)
5. OBSERVE result:
   - SUCCESS → store output in context, mark step complete
   - FAILURE → enter recovery:
     a. If retries < max_retries → retry same tool (increment retry count)
     b. If fallback_tools available → try next fallback tool
     c. If no fallbacks remain → invoke LLM re-planner for this step
     d. If re-plan fails and priority == CRITICAL → abort plan
     e. If re-plan fails and priority < CRITICAL → skip step, log warning
6. LOG step execution details (timing, tool used, result, errors)
```

### 7.2 Dependency Resolution

Steps declare dependencies via `depends_on` (list of step IDs). The orchestrator builds a DAG and executes in topological order. Independent steps *may* execute in parallel (future enhancement), but the initial implementation processes sequentially.

```python
def resolve_execution_order(steps: list[Step]) -> list[Step]:
    """Topological sort of steps based on depends_on relationships."""
    from collections import deque

    in_degree = {s.id: 0 for s in steps}
    adjacency = {s.id: [] for s in steps}
    step_map = {s.id: s for s in steps}

    for step in steps:
        for dep_id in step.depends_on:
            adjacency[dep_id].append(step.id)
            in_degree[step.id] += 1

    queue = deque([sid for sid, deg in in_degree.items() if deg == 0])
    ordered = []

    while queue:
        sid = queue.popleft()
        ordered.append(step_map[sid])

        for neighbor in adjacency[sid]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(ordered) != len(steps):
        raise ValueError("Circular dependency detected in execution plan")

    return ordered
```

### 7.3 Failure Recovery Strategy

The failure recovery system operates on a **cascade model**:

```text
FAILURE DETECTED
      │
      ├─ Level 1: RETRY (same tool, same input)
      │  └─ Up to max_retries attempts with exponential backoff
      │
      ├─ Level 2: FALLBACK TOOL (different tool, same goal)
      │  └─ Try each tool in fallback_tools list
      │
      ├─ Level 3: RE-PLAN (LLM generates alternative approach)
      │  └─ Send error context to LLM, get new step definition
      │
      └─ Level 4: ESCALATE
         ├─ CRITICAL priority → Abort entire plan, report error
         ├─ HIGH priority → Log error, continue with degraded output
         ├─ MEDIUM priority → Skip step, note in output
         └─ LOW priority → Skip silently
```

### 7.4 Context Management

The shared context is an in-memory dictionary that accumulates state:

```python
context = {
    "config": {
        "llm_model": "gpt-4o",
        "max_tokens": 4096,
        "output_dir": "./output",
    },
    "step_results": {
        "step_0": {"status": "success", "output": [...search results...]},
        "step_1": {"status": "success", "output": "extracted data..."},
    },
    "variables": {
        "research_topic": "GPT-4 usage",
        "output_filename": "gpt4_summary.pdf",
    },
    "errors": [
        {"step_id": "step_0", "attempt": 1, "error": "Rate limited", "recovered": True}
    ],
    "files_created": ["./output/gpt4_summary.pdf"],
}
```

---

## 8. Planner System

### 8.1 Planning Prompt Template

```python
PLANNING_SYSTEM_PROMPT = """You are a task planning agent. Given a user's request, decompose it into a structured execution plan with ordered steps. Available tools: {tool_descriptions}

For each step, specify:
- description: What this step accomplishes
- tool_hint: Which tool to use (from available tools)
- input_data: Parameters for the tool
- priority: "critical" | "high" | "medium" | "low"
- depends_on: List of step indices this step depends on (e.g., ["step_0"])
- fallback_tools: Alternative tools if the primary fails

Rules:
1. Break complex tasks into atomic, testable steps
2. Each step should have a single clear objective
3. Declare dependencies explicitly — don't assume sequential execution
4. Always include fallback tools where alternatives exist
5. Mark steps that produce the final deliverable as "critical" priority
6. Prefer specific tool hints over generic ones

Respond with valid JSON matching the ExecutionPlan schema."""
```

### 8.2 Re-Planning Prompt (Failure Recovery)

```python
REPLAN_PROMPT = """A step in the execution plan has failed after all retries and fallbacks.

Failed step: {step_description}
Tool used: {tool_name}
Error: {error_message}
Previous attempts: {attempt_history}
Available tools: {tool_descriptions}
Current context: {context_summary}

Generate an alternative step (or sequence of steps) to achieve the same goal using a different approach. Respond with valid JSON."""
```

---

## 9. Security & Sandboxing

### 9.1 Code Execution Sandbox

The `code_execute` tool runs Python code in a restricted subprocess:

```python
import subprocess
import tempfile
import os

class CodeSandbox:
    """Sandboxed Python code execution via subprocess."""

    TIMEOUT_SECONDS = 30
    MAX_OUTPUT_BYTES = 1_000_000  # 1MB

    # Commands/modules that are blocked
    BLOCKED_PATTERNS = [
        "import os; os.system",
        "subprocess",
        "shutil.rmtree",
        "__import__('os').system",
        "eval(",
        "exec(",
        "open('/etc",
        "open('C:\\\\Windows",
    ]

    def execute(self, code: str, timeout: int | None = None) -> ToolResult:
        timeout = timeout or self.TIMEOUT_SECONDS

        # Basic static analysis
        for pattern in self.BLOCKED_PATTERNS:
            if pattern in code:
                return ToolResult(
                    success=False,
                    error=f"Blocked pattern detected: {pattern}"
                )

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', delete=False
        ) as f:
            f.write(code)
            temp_path = f.name

        try:
            result = subprocess.run(
                ["python", temp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tempfile.gettempdir(),
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONPATH": "",
                },
            )

            output = result.stdout[:self.MAX_OUTPUT_BYTES]

            if result.returncode == 0:
                return ToolResult(success=True, output=output)
            else:
                return ToolResult(
                    success=False,
                    output=output,
                    error=result.stderr[:self.MAX_OUTPUT_BYTES]
                )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error=f"Code execution timed out ({timeout}s)"
            )

        finally:
            os.unlink(temp_path)
```

### 9.2 Shell Command Whitelist

```python
WHITELISTED_COMMANDS = {
    "ls",
    "dir",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "find",
    "echo",
    "date",
    "pwd",
    "python",
    "pip",
    "node",
    "npm",
    "git status",
    "git log",
    "git diff",
    "curl",
    "wget",
}
```

### 9.3 Data Privacy Controls

- All execution is local by default.
- Only the LLM API calls transmit data externally.
- A configurable `sensitive_data_filter` can redact patterns (SSN, API keys, emails) before sending to LLM.
- Users are warned at startup if `.env` contains keys that will be transmitted.

---

## 10. Logging & Observability

### 10.1 Log Structure

Every action produces a structured log entry:

```json
{
  "timestamp": "2024-12-15T10:23:45.123Z",
  "level": "INFO",
  "component": "orchestrator",
  "event": "step_completed",
  "step_id": "a1b2c3d4",
  "step_description": "Search for GPT-4 usage statistics",
  "tool_name": "web_search",
  "duration_ms": 2340,
  "status": "success",
  "retry_count": 0,
  "context_size_bytes": 4521,
  "llm_tokens_used": 0,
  "metadata": {
    "results_count": 10,
    "query": "GPT-4 usage statistics 2024"
  }
}
```

### 10.2 Execution Report

At plan completion, the harness generates a full execution report:

```text
═══════════════════════════════════════════════════════════
EXECUTION REPORT
═══════════════════════════════════════════════════════════
Plan ID: a1b2c3d4
Prompt: "Research GPT-4 usage and build a summary PDF"
Status: COMPLETED
Duration: 45.2s
Steps: 4 total | 3 success | 1 retried (recovered)
LLM Tokens: 12,340 (est. cost: $0.037)
Files Created: ./output/gpt4_summary.pdf

Step Details:
[✓] Step 1: Web search for GPT-4 statistics (2.3s, web_search)
[✓] Step 2: Extract key data points (8.1s, llm_extract)
[⟳] Step 3: Generate comparison table (12.4s, code_execute, 1 retry)
[✓] Step 4: Export summary as PDF (5.8s, pdf_export)

Errors Encountered:
Step 3, Attempt 1: SyntaxError in generated code → retried with error context
═══════════════════════════════════════════════════════════
```

---

## 11. Configuration

### 11.1 Configuration File (`config.yaml`)

```yaml
# Agent Harness Configuration

llm:
  provider: "openai"              # openai | anthropic | local
  model: "gpt-4o"                 # Model identifier
  api_key_env: "OPENAI_API_KEY"   # Environment variable name
  base_url: null                  # Override for local/proxy models
  max_tokens: 4096                # Max tokens per LLM call
  temperature: 0.2                # Lower = more deterministic planning
  timeout: 60                      # Seconds per LLM call

execution:
  max_steps: 20                   # Maximum steps per plan
  step_timeout: 120               # Seconds per step
  max_retries: 2                  # Default retries per step
  retry_backoff: "exponential"    # exponential | linear | fixed
  retry_base_delay: 2             # Seconds
  output_dir: "./output"          # Where to write output files
  temp_dir: "./tmp"               # Temporary files during execution

search:
  provider: "duckduckgo"          # serpapi | bing | duckduckgo | google
  api_key_env: "SEARCH_API_KEY"    # Only needed for serpapi/bing
  max_results: 10                  # Results per search query

security:
  sandbox_code: true              # Run code in subprocess sandbox
  code_timeout: 30                # Seconds for code execution
  max_output_bytes: 1000000        # 1MB max output per tool block
  network_in_code: false           # Block network access in code sandbox
  sensitive_patterns:             # Patterns to redact before LLM calls
    - "\\b\\d{3}-\\d{2}-\\d{4}\\b" # SSN
    - "sk-[a-zA-Z0-9]{48}"         # OpenAI API keys

logging:
  level: "INFO"                   # DEBUG | INFO | WARNING | ERROR
  file: "./logs/agent_harness.log" # Log file path
  format: "json"                  # json | text
  console: true                   # Also log to console

plugins:
  dirs:                            # Directories to scan for custom tools
    - "./plugins"
    - "~/.agent_harness/plugins"
  auto_load: true                  # Auto-register discovered tools
```

### 11.2 Environment Variables

```bash
# .env file
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
SEARCH_API_KEY=...                # SerpAPI or Bing key (optional)
AGENT_HARNESS_CONFIG=./config.yaml # Config file path override
AGENT_HARNESS_LOG_LEVEL=DEBUG     # Override log level
```

---

## 12. User Stories — Detailed

### US-1: End-to-End Research Automation

**As a** student, **I want to** enter "Research the top 5 AI models of 2024, compare them, and create a PDF report"

**So that** I receive a complete PDF report without manually searching, reading, or formatting.

**Acceptance Criteria:**

- [ ] Agent decomposes prompt into ≥3 steps (search, analyze, generate report)
- [ ] Each step uses appropriate tool (web_search, llm_extract, pdf_export)
- [ ] Final PDF is created in the output directory
- [ ] If web search fails, agent retries with alternative search provider
- [ ] Execution report shows all steps and their outcomes

### US-2: Code Generation and Execution

**As a** developer, **I want to** enter "Write a Python script that reads data.csv and generates a bar chart of sales by region, save as chart.png"

**So that** I get working code executed automatically with the chart file created.

**Acceptance Criteria:**

- [ ] Agent generates Python code using LLM
- [ ] Code is executed in sandbox
- [ ] If code fails (syntax error, missing library), agent fixes and retries
- [ ] chart.png is created in output directory
- [ ] Generated code is saved alongside output for review

### US-3: Self-Recovery on Failure

**As a** researcher, **I want** the agent to automatically recover when a web search returns no results

**So that** my workflow completes even when individual data sources are unavailable.

**Acceptance Criteria:**

- [ ] Agent attempts primary search tool
- [ ] On failure, tries fallback tool (different search provider or web scrape)
- [ ] On continued failure, asks LLM to re-plan with alternative approach
- [ ] If step is non-critical and all recovery fails, agent continues with available data
- [ ] All recovery attempts are logged with error details

### US-4: Custom Tool Integration

**As a** power user, **I want** to add a custom Slack notification tool

**So that** the agent notifies me when a long-running plan completes.

**Acceptance Criteria:**

- [ ] User creates a Python file implementing `BaseTool`
- [ ] Places it in the plugins directory
- [ ] Agent auto-discovers and registers the tool on startup
- [ ] LLM can select the tool when the user's prompt mentions notification
- [ ] Tool appears in `list_tools()` output

---

## 13. Error Handling Specification

### 13.1 Error Categories

| Category | Examples | Handling |
|---|---|---|
| **LLM Errors** | API timeout, rate limit, invalid response | Retry with exponential backoff; fallback to cheaper model |
| **Tool Errors** | Search API down, file not found, code syntax error | Tool-level retry → fallback tool → re-plan |
| **Planning Errors** | Circular dependencies, invalid step references | Validate plan before execution; re-plan if invalid |
| **System Errors** | Disk full, permission denied, OOM | Abort with clear error message; suggest fixes |
| **User Input Errors** | Empty prompt, unsupported language | Validate at entry; prompt for clarification |

### 13.2 Error Response Contract

All components return errors in a standardized format:

```python
@dataclass
class AgentError:
    code: str                 # e.g., "TOOL_EXECUTION_FAILED"
    message: str              # Human-readable description
    component: str             # Which component raised it
    step_id: str | None        # Which step (if applicable)
    recoverable: bool          # Whether automatic recovery was attempted
    recovery_action: str | None # What recovery was taken
    original_error: str | None # Raw error message/traceback
```

---

## 14. Success Metrics

### 14.1 Core Metrics

| Metric | Target | Measurement |
|---|---|---|
| **Plan Completion Rate** | ≥85% of prompts produce a complete output | `completed_plans / total_plans` |
| **Step Success Rate** | ≥90% of steps succeed (including retries) | `successful_steps / total_steps` |
| **Recovery Success Rate** | ≥70% of failed steps recovered via retry/fallback | `recovered_steps / failed_steps` |
| **Time to First Output** | <60s for simple tasks, <5min for complex research | Median time from prompt to final output |
| **Setup Success Rate** | ≥95% of users complete setup on first try | Tracked via install script exit codes |
| **LLM Efficiency** | <15,000 tokens per average plan | Sum of all LLM calls per plan |

### 14.2 Tracking Implementation

```python
@dataclass
class ExecutionMetrics:
    plan_id: str
    prompt_length: int
    total_steps: int
    successful_steps: int
    failed_steps: int
    recovered_steps: int
    skipped_steps: int
    total_retries: int
    total_duration_ms: int
    llm_calls: int
    llm_tokens_used: int
    llm_estimated_cost: float
    tools_used: list[str]
    files_created: list[str]
    errors: list[dict]
```

---

## 15. Milestones & Delivery Plan

### Phase 1: Core Engine (Days 1–4)

| Deliverable | Description | Owner |
|---|---|---|
| Data model | `Step`, `ExecutionPlan`, `ToolResult`, `AgentError` types | Dev |
| Planner | LLM-based prompt decomposition with structured output | Dev |
| Orchestrator | Core POEA loop with dependency resolution | Dev |
| Tool interface | `BaseTool` ABC, `ToolRegistry` | Dev |
| Built-in tools | `web_search` (DuckDuckGo), `code_execute`, `file_read`, `file_write`, `llm_extract` | Dev |
| Failure recovery | Retry, fallback, re-plan cascade | Dev |
| CLI entry point | `python -m agent_harness "Your prompt here"` | Dev |
| Config system | `config.yaml` + `.env` loading | Dev |

### Phase 2: Extended Tools & Polish (Days 5–7)

| Deliverable | Description | Owner |
|---|---|---|
| Additional tools | `web_scrape`, `pdf_export`, `csv_process`, `shell_command`, `llm_synthesize` | Dev |
| Plugin auto-discovery | Scan plugin directories, auto-register tools | Dev |
| Assembler | Multi-format output assembly (text, markdown, PDF, files) | Dev |
| Execution report | Formatted execution summary with metrics | Dev |
| Structured logging | JSON log output with all execution events | Dev |
| Security hardening | Code sandbox improvements, input validation | Dev |

### Phase 3: Documentation, Testing & Demo (Days 8–10)

| Deliverable | Description | Owner |
|---|---|---|
| Developer README | Full setup, usage, extension guide (this document, Part 2) | Dev |
| API documentation | Docstrings, type hints, module-level docs | Dev |
| Test suite | Unit tests for each component, integration test for full plan execution | Dev |
| Demo scripts | 3 example prompts with expected outputs | Dev |
| Sample plugins | 2 example custom tools with documentation | Dev |

---

## 16. Open Questions & Future Work

| Item | Status | Notes |
|---|---|---|
| Parallel step execution | **Deferred** | Independent steps could run concurrently; adds complexity |
| Streaming output | **Deferred** | Stream LLM responses and tool outputs in real-time |
| Web UI | **Deferred** | Flask/FastAPI front-end with step visualization |
| Persistent memory | **Deferred** | Cross-session context via SQLite or vector store |
| Multi-agent collaboration | **Out of scope** | Multiple agents coordinating on sub-plans |
| Cost budgets | **Phase 2** | Set max $ spend per plan; abort if exceeded |
| Human-in-the-loop | **Phase 2** | Pause before critical steps for user confirmation |

---

---

# PART 2: DEVELOPER README

---

# Agent Harness — Developer Guide

**Local-first autonomous agent execution framework**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Usage](#usage)
6. [Architecture Deep Dive](#architecture-deep-dive)
7. [Built-in Tools Reference](#built-in-tools-reference)
8. [Writing Custom Tools](#writing-custom-tools)
9. [Failure Recovery System](#failure-recovery-system)
10. [Testing](#testing)
11. [Project Structure](#project-structure)
12. [Troubleshooting](#troubleshooting)
13. [Contributing](#contributing)

---

## Quick Start

```bash
# Clone the repository
git clone https://github.com/yourusername/agent-harness.git
cd agent-harness

# Create virtual environment and install
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

pip install -e ".[dev]"

# Set up your API key
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# Run your first agent task
python -m agent_harness "Search for the top 3 Python web frameworks and create a comparison table"
```

**Expected output:** The agent will decompose the prompt, search the web, extract data, generate a comparison table, and save it to `./output/`.

---

## Prerequisites

| Requirement | Version | Required | Notes |
|---|---|---|---|
| Python | 3.9+ | ✅ | 3.11+ recommended |
| pip | 21.0+ | ✅ | For editable installs |
| OpenAI API Key | — | ✅ | Or any OpenAI-compatible API |
| Git | 2.0+ | ✅ | For cloning |
| SerpAPI Key | — | ❌ | Optional; DuckDuckGo is the free default |
| wkhtmltopdf | 0.12+ | ❌ | Only needed for PDF export tool |

### System-Specific Notes

**macOS:**

```bash
brew install wkhtmltopdf # Optional, for PDF export
```

**Ubuntu/Debian:**

```bash
sudo apt-get install wkhtmltopdf # Optional, for PDF export
```

**Windows:**

- Download wkhtmltopdf from [wkhtmltopdf.org](https://wkhtmltopdf.org/downloads.html) (optional)
- Use PowerShell or WSL for best experience

---

## Installation

### Standard Installation

```bash
git clone https://github.com/yourusername/agent-harness.git
cd agent-harness

python -m venv venv
source venv/bin/activate

pip install -e .
```

### Development Installation (with test/lint tools)

```bash
pip install -e ".[dev]"
```

### Dependencies

The `pyproject.toml` manages all dependencies:

```toml
[project]
name = "agent-harness"
version = "0.1.0"
requires-python = ">=3.9"

dependencies = [
    "openai>=1.12.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0.0",
    "requests>=2.31.0",
    "beautifulsoup4>=4.12.0",
    "duckduckgo-search>=4.0",
    "pdfkit>=1.0.0",
    "rich>=13.0.0",              # Pretty console output
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "ruff>=0.1.0",
    "mypy>=1.0",
]

anthropic = [
    "anthropic>=0.18.0",
]
```

---

## Configuration

### Step 1: Environment Variables

Copy the example and fill in your keys:

```bash
cp .env.example .env
```

```bash
# .env
OPENAI_API_KEY=sk-your-key-here

# Optional: for SerpAPI web search (otherwise DuckDuckGo is used)
SEARCH_API_KEY=your-serpapi-key

# Optional: for Anthropic models
ANTHROPIC_API_KEY=sk-ant-your-key-here

# Optional: override config file location
AGENT_HARNESS_CONFIG=./config.yaml
```

### Step 2: Configuration File

The default `config.yaml` works out of the box. Customize as needed:

```yaml
llm:
  provider: "openai"
  model: "gpt-4o"
  api_key_env: "OPENAI_API_KEY"
  temperature: 0.2
  max_tokens: 4096

execution:
  max_steps: 20
  step_timeout: 120
  max_retries: 2
  output_dir: "./output"

search:
  provider: "duckduckgo" # Free, no API key needed
  max_results: 10

security:
  sandbox_code: true
  code_timeout: 30

logging:
  level: "INFO"
  file: "./logs/agent_harness.log"
  format: "json"
  console: true

plugins:
  dirs: ["./plugins"]
  auto_load: true
```

### Using Local/Self-Hosted Models

For Ollama, LM Studio, or any OpenAI-compatible API:

```yaml
llm:
  provider: "openai"              # Still use openai provider
  model: "llama3"                # Your local model name
  base_url: "http://localhost:11434/v1" # Ollama default
  api_key_env: "OPENAI_API_KEY"   # Set to "ollama" or any string
```

---

## Usage

### CLI (Primary Interface)

```bash
# Basic usage
python -m agent_harness "Your task description here"

# With options
python -m agent_harness "Research quantum computing basics" \
  --config ./config.yaml \
  --output-dir ./my_output \
  --log-level DEBUG \
  --dry-run # Show plan without executing

# List available tools
python -m agent_harness --list-tools

# Run with a specific config
python -m agent_harness --config ./custom_config.yaml "Your task"
```

### CLI Argument Reference

```text
usage: python -m agent_harness [-h] [--config PATH] [--output-dir DIR] [--log-level LEVEL] [--dry-run] [--list-tools] [--max-steps N] [--no-fallback] [prompt]

positional arguments:
  prompt                 Natural language task description

optional arguments:
  -h, --help             Show help message
  --config PATH          Path to config.yaml (default: ./config.yaml)
  --output-dir DIR       Output directory (overrides config)
  --log-level LEVEL      Logging level: DEBUG|INFO|WARNING|ERROR
  --dry-run              Generate and display plan without executing
  --list-tools           List all registered tools and exit
  --max-steps N          Override max steps per plan
  --no-fallback          Disable automatic fallback/re-planning
```

### Python API (Programmatic Usage)

```python
from agent_harness import AgentHarness, Config

# Initialize
config = Config.from_file("./config.yaml")
harness = AgentHarness(config)

# Run a task
result = harness.run("Research the latest trends in AI safety and write a summary")

# Access results
print(result.status)          # "completed" | "failed" | "partial"
print(result.final_output)    # The assembled output text/data
print(result.plan)            # The ExecutionPlan with all step details
print(result.metrics)         # ExecutionMetrics with timing, tokens, costs
print(result.files_created)   # List of output file paths

# Run with custom context
result = harness.run(
    prompt="Analyze this data and create a chart",
    context={"data_file": "./data/sales.csv"},
    output_format="markdown",
)

# Dry run (plan only, no execution)
plan = harness.plan("Build a REST API for a todo app")
for step in plan.steps:
    print(f" [{step.tool_hint}] {step.description}")
```

### Registering Custom Tools at Runtime

```python
from agent_harness import AgentHarness, Config
from my_tools import DatabaseQueryTool, EmailTool

config = Config.from_file("./config.yaml")
harness = AgentHarness(config)

# Register custom tools
harness.register_tool(DatabaseQueryTool(connection_string="sqlite:///mydb.db"))
harness.register_tool(EmailTool(smtp_host="smtp.gmail.com"))

# Now the agent can use these tools
result = harness.run("Query all users from the database and email a summary to admin@example.com")
```

---

## Architecture Deep Dive

### Module Dependency Graph

```text
agent_harness/
│
├── __main__.py                 ← CLI entry point
├── harness.py                  ← AgentHarness (top-level API)
│
├── planning/
│   ├── planner.py              ← LLM-based task decomposition
│   └── prompts.py              ← System prompts for planning/re-planning
│
├── orchestration/
│   ├── orchestrator.py         ← Core POEA execution loop
│   ├── dependency.py           ← DAG resolution / topological sort
│   └── recovery.py             ← Retry, fallback, re-plan logic
│
├── tools/
│   ├── base.py                 ← BaseTool ABC, ToolResult, ToolRegistry
│   ├── web_search.py           ← Web search (DuckDuckGo, SerpAPI)
│   ├── web_scrape.py           ← URL content extraction
│   ├── code_execute.py         ← Sandboxed Python execution
│   ├── file_read.py            ← File reading (TXT, CSV, JSON, PDF)
│   ├── file_write.py           ← File writing
│   ├── llm_extract.py          ← LLM-based data extraction
│   ├── llm_synthesize.py       ← LLM-based content generation
│   ├── pdf_export.py           ← Markdown/HTML → PDF conversion
│   ├── csv_process.py          ← CSV data operations
│   └── shell_command.py        ← Whitelisted shell commands
│
├── context/
│   └── store.py                ← Shared context management
│
├── config/
│   ├── loader.py               ← Config file and env loading
│   └── schema.py               ← Config validation
│
├── logging/
│   ├── logger.py               ← Structured logging
│   └── report.py               ← Execution report generation
│
└── plugins/
    └── loader.py               ← Plugin directory scanner and auto-registration
```

### Request Lifecycle (Detailed)

```text
1. USER INPUT
   └─ CLI parses arguments, loads config, initializes AgentHarness

2. HARNESS.RUN(prompt)
   ├─ Validates prompt (non-empty, reasonable length)
   ├─ Initializes fresh Context
   └─ Calls Planner.plan(prompt, available_tools)

3. PLANNER
   ├─ Constructs system prompt with tool descriptions
   ├─ Calls LLM with structured output schema
   ├─ Parses response into ExecutionPlan
   ├─ Validates plan (no circular deps, all tool hints valid)
   └─ Returns ExecutionPlan

4. ORCHESTRATOR.EXECUTE(plan)
   ├─ Resolves execution order (topological sort)
   ├─ FOR EACH step:
   │  ├─ Checks dependency completion
   │  ├─ Resolves tool (tool_hint → ToolRegistry lookup)
   │  ├─ Prepares input (injects context, dependency outputs)
   │  ├─ Calls tool.execute(input_data, context)
   │  ├─ Evaluates ToolResult:
   │  │  ├─ SUCCESS → store output, update context, log
   │  │  └─ FAILURE → enter Recovery
   │  └─ Updates step status and timing
   └─ Returns completed plan with all results

5. RECOVERY (on failure)
   ├─ Level 1: Retry same tool (up to max_retries)
   ├─ Level 2: Try fallback tools in order
   ├─ Level 3: Call Planner.replan(failed_step, error, context)
   └─ Level 4: Skip (if non-critical) or abort (if critical)

6. ASSEMBLER
   ├─ Collects all step outputs from context
   ├─ Calls LLM to synthesize final output (if needed)
   ├─ Writes output files
   └─ Returns final result

7. REPORTING
   ├─ Generates ExecutionMetrics
   ├─ Produces formatted execution report
   ├─ Writes log file
   └─ Returns HarnessResult to caller
```

---

## Built-in Tools Reference

### `web_search`

Searches the web using DuckDuckGo (default) or SerpAPI.

```python
# Input
{
    "query": "Python web frameworks comparison 2024",
    "num_results": 10,  # Optional, default: config value
    "region": "us-en"   # Optional
}

# Output (ToolResult.output)
[
    {
        "title": "Best Python Web Frameworks in 2024",
        "url": "https://example.com/article",
        "snippet": "Django, Flask, and FastAPI lead the pack..."
    },
    ...
]
```

### `web_scrape`

Fetches a URL and extracts text content.

```python
# Input
{
    "url": "https://example.com/article",
    "selector": "article.main-content",  # Optional CSS selector
    "max_length": 5000                    # Optional character limit
}

# Output (ToolResult.output)
"Extracted text content from the page..."
```

### `code_execute`

Runs Python code in a sandboxed subprocess.

```python
# Input — direct code
{
    "code": "import json\ndata = {'key': 'value'}\nprint(json.dumps(data, indent=2))"
}

# Input — task description (LLM generates code)
{
    "task": "Read sales.csv and calculate total revenue by region",
    "language": "python"
}

# Output (ToolResult.output)
"{
 \"key\": \"value\"
}"
```

### `file_read`

Reads local files in common formats.

```python
# Input
{
    "path": "./data/report.csv",
    "format": "csv",       # auto-detected if omitted
    "encoding": "utf-8"    # Optional
}

# Output varies by format:
# CSV → list of dicts
# JSON → parsed object
# TXT/MD → string
# PDF → extracted text
```

### `file_write`

Writes content to local files.

```python
# Input
{
    "path": "./output/summary.md",
    "content": "# Summary\n\nThis is the summary...",
    "format": "markdown",  # Optional
    "create_dirs": true    # Create parent directories if missing
}

# Output (ToolResult.output)
"./output/summary.md"      # Confirmed file path
```

### `llm_extract`

Uses the LLM to extract structured information from text.

```python
# Input
{
    "input_text": "Long article text here...",
    "instruction": "Extract all mentioned statistics as a JSON list with fields: metric, value, source",
    "output_format": "json"  # Optional: json | text | markdown
}

# Output (ToolResult.output)
[
    {"metric": "GPT-4 users", "value": "100M", "source": "OpenAI blog"},
    ...
]
```

### `llm_synthesize`

Uses the LLM to generate new content from context.

```python
# Input
{
    "instruction": "Write a one-page executive summary based on the research findings",
    "sources": ["step_0_output", "step_1_output"],  # References to context
    "tone": "professional",                         # Optional
    "max_words": 500                                # Optional
}

# Output (ToolResult.output)
"Executive Summary\n\n..."
```

### `pdf_export`

Converts markdown or HTML content to PDF.

```python
# Input
{
    "content": "# Report Title\n\n...",  # Markdown or HTML
    "filename": "report.pdf",
    "format": "markdown",                # markdown | html
    "page_size": "A4"                    # Optional
}

# Output (ToolResult.output)
"./output/report.pdf"                    # Created file path
```

### `csv_process`

Reads and transforms CSV data.

```python
# Input
{
    "path": "./data/sales.csv",
    "operations": [
        {"type": "filter", "column": "region", "value": "US"},
        {"type": "sort", "column": "revenue", "order": "desc"},
        {"type": "head", "n": 10}
    ],
    "output_path": "./output/us_sales.csv" # Optional: save result
}

# Output (ToolResult.output)
[
    {"region": "US", "revenue": 50000, ...},
    ...
]
```

---

## Writing Custom Tools

### Minimal Example

```python
# plugins/hello_tool.py
from agent_harness.tools.base import BaseTool, ToolResult

class HelloTool(BaseTool):
    """A simple example tool that greets the user."""

    @property
    def name(self) -> str:
        return "hello"

    @property
    def description(self) -> str:
        return "Says hello with a custom message. Use for testing."

    @property
    def capabilities(self) -> list[str]:
        return ["greeting", "testing"]

    def execute(self, input_data: dict, context: dict) -> ToolResult:
        name = input_data.get("name", "World")
        message = f"Hello, {name}! The agent harness is working."
        return ToolResult(success=True, output=message)
```

### Full-Featured Example

```python
# plugins/database_query.py
import sqlite3
from agent_harness.tools.base import BaseTool, ToolResult

class DatabaseQueryTool(BaseTool):
    """Executes read-only SQL queries against a SQLite database."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    @property
    def name(self) -> str:
        return "database_query"

    @property
    def description(self) -> str:
        return (
            f"Executes read-only SQL queries against the SQLite database "
            f"at {self._db_path}. Input: {{query: 'SELECT ...'}}"
        )

    @property
    def capabilities(self) -> list[str]:
        return ["database", "sql", "data_retrieval"]

    def validate_input(self, input_data: dict) -> tuple[bool, str]:
        if "query" not in input_data:
            return False, "Missing required 'query' field"

        query = input_data["query"].strip().upper()

        if not query.startswith("SELECT"):
            return False, "Only SELECT queries are allowed (read-only)"

        dangerous = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE"]

        for keyword in dangerous:
            if keyword in query:
                return False, f"Dangerous keyword '{keyword}' detected"

        return True, ""

    def execute(self, input_data: dict, context: dict) -> ToolResult:
        is_valid, error_msg = self.validate_input(input_data)

        if not is_valid:
            return ToolResult(success=False, error=error_msg)

        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row

            cursor = conn.cursor()
            cursor.execute(input_data["query"])

            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()

            return ToolResult(
                success=True,
                output=rows,
                metadata={"row_count": len(rows), "db_path": self._db_path},
            )

        except sqlite3.Error as e:
            return ToolResult(success=False, error=f"SQLite error: {e}")

        except Exception as e:
            return ToolResult(success=False, error=f"Unexpected error: {e}")

    def cleanup(self) -> None:
        pass  # Connection is opened/closed per query
```

### Plugin Auto-Discovery

Place your tool file in any directory listed under `plugins.dirs` in `config.yaml`. The plugin loader scans for classes that subclass `BaseTool`:

```python
# How auto-discovery works (agent_harness/plugins/loader.py)
import importlib.util
import inspect
from pathlib import Path
from agent_harness.tools.base import BaseTool

def discover_tools(plugin_dirs: list[str]) -> list[type[BaseTool]]:
    """Scan directories for BaseTool subclasses."""
    tools = []

    for dir_path in plugin_dirs:
        path = Path(dir_path).expanduser()

        if not path.exists():
            continue

        for py_file in path.glob("*.py"):
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, BaseTool) and obj is not BaseTool:
                    tools.append(obj)

    return tools
```

### Manual Registration

```python
from agent_harness import AgentHarness
from plugins.database_query import DatabaseQueryTool

harness = AgentHarness.from_config("./config.yaml")
harness.register_tool(DatabaseQueryTool(db_path="./data/app.db"))
```

---

## Failure Recovery System

### How Recovery Works

The recovery system is implemented in `agent_harness/orchestration/recovery.py`:

```python
class RecoveryManager:
    """Manages failure recovery for step execution."""

    def __init__(self, planner, tool_registry, config):
        self.planner = planner
        self.registry = tool_registry
        self.config = config

    def attempt_recovery(
        self,
        step: Step,
        error: str,
        context: dict,
    ) -> tuple[bool, ToolResult | None]:
        """
        Attempt to recover from a step failure.

        Returns:
            (recovered: bool, result: ToolResult or None)
        """

        # Level 1: Retry same tool
        if step.retries < step.max_retries:
            step.retries += 1
            step.status = StepStatus.RETRYING

            delay = self._backoff_delay(step.retries)
            time.sleep(delay)

            tool = self.registry.get(step.tool_name)
            result = tool.execute(step.input_data, context)

            if result.success:
                return True, result

        # Level 2: Try fallback tools
        for fallback_name in step.fallback_tools:
            fallback_tool = self.registry.get(fallback_name)

            if fallback_tool is None:
                continue

            result = fallback_tool.execute(step.input_data, context)

            if result.success:
                step.tool_name = fallback_name  # Record which tool succeeded
                return True, result

        # Level 3: Ask LLM to re-plan this step
        new_steps = self.planner.replan_step(step, error, context)

        if new_steps:
            for new_step in new_steps:
                tool = self.registry.get(new_step.tool_name)

                if tool:
                    result = tool.execute(new_step.input_data, context)

                    if result.success:
                        return True, result

        # Level 4: Escalate based on priority
        return False, None

    def _backoff_delay(self, retry_count: int) -> float:
        """Exponential backoff: 2s, 4s, 8s, ..."""
        base = self.config.execution.retry_base_delay
        return base * (2 ** (retry_count - 1))
```

### Recovery Configuration

```yaml
execution:
  max_retries: 2                    # Per-step retry limit
  retry_backoff: "exponential"     # exponential | linear | fixed
  retry_base_delay: 2              # Seconds
  enable_replan: true              # Allow LLM re-planning on failure
  abort_on_critical_failure: true  # Abort entire plan if critical step fails
```

### Testing Recovery

```bash
# Force a failure to test recovery
python -m agent_harness "Search for 'xyznonexistentquery12345' and summarize the results" \
  --log-level DEBUG

# The agent should:
# 1. Search → get no/poor results
# 2. Retry with refined query
# 3. Fall back to alternative search
# 4. Re-plan with different approach
# 5. Eventually produce a "no information found" report or alternative output
```

---

## Testing

### Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=agent_harness --cov-report=html

# Specific test module
pytest tests/test_orchestrator.py -v

# Only unit tests (no API calls)
pytest -m "not integration"

# Integration tests (requires API key)
pytest -m integration
```

### Test Structure

```text
tests/
├── conftest.py                    # Shared fixtures
├── test_planner.py                # Planning/decomposition tests
├── test_orchestrator.py           # Core loop and dependency tests
├── test_recovery.py               # Failure recovery scenarios
├── test_tools/
│   ├── test_web_search.py
│   ├── test_code_execute.py
│   ├── test_file_ops.py
│   └── test_llm_tools.py
├── test_context.py                # Context management
├── test_config.py                 # Configuration loading
├── test_plugin_loader.py          # Plugin discovery
└── integration/
    ├── test_full_plan.py          # End-to-end plan execution
    └── test_recovery_e2e.py       # End-to-end recovery scenarios
```

### Example Test

```python
# tests/test_orchestrator.py
import pytest
from agent_harness.orchestration.orchestrator import Orchestrator
from agent_harness.orchestration.dependency import resolve_execution_order
from agent_harness.tools.base import BaseTool, ToolResult, ToolRegistry
from agent_harness.config.schema import ExecutionPlan, Step, StepStatus

class MockTool(BaseTool):
    name = "mock_tool"
    description = "A mock tool for testing"

    def __init__(self, should_fail=False):
        self._should_fail = should_fail

    def execute(self, input_data, context):
        if self._should_fail:
            return ToolResult(success=False, error="Mock failure")
        return ToolResult(success=True, output=f"Mock output for: {input_data}")

class TestDependencyResolution:
    def test_linear_dependencies(self):
        steps = [
            Step(id="a", depends_on=[]),
            Step(id="b", depends_on=["a"]),
            Step(id="c", depends_on=["b"]),
        ]

        ordered = resolve_execution_order(steps)
        ids = [s.id for s in ordered]

        assert ids == ["a", "b", "c"]

    def test_diamond_dependencies(self):
        steps = [
            Step(id="a", depends_on=[]),
            Step(id="b", depends_on=["a"]),
            Step(id="c", depends_on=["a"]),
            Step(id="d", depends_on=["b", "c"]),
        ]

        ordered = resolve_execution_order(steps)
        ids = [s.id for s in ordered]

        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")

    def test_circular_dependency_raises(self):
        steps = [
            Step(id="a", depends_on=["b"]),
            Step(id="b", depends_on=["a"]),
        ]

        with pytest.raises(ValueError, match="Circular dependency"):
            resolve_execution_order(steps)

class TestOrchestrator:
    def test_successful_execution(self):
        registry = ToolRegistry()
        registry.register(MockTool())

        plan = ExecutionPlan(
            original_prompt="Test",
            steps=[
                Step(
                    id="s1",
                    tool_name="mock_tool",
                    input_data={"key": "val"}
                ),
            ],
        )

        orchestrator = Orchestrator(
            registry=registry,
            config=MockConfig()
        )

        result = orchestrator.execute(plan)

        assert result.status == StepStatus.SUCCESS
        assert result.steps[0].status == StepStatus.SUCCESS

    def test_failure_triggers_retry(self):
        registry = ToolRegistry()
        registry.register(MockTool(should_fail=True))

        plan = ExecutionPlan(
            original_prompt="Test",
            steps=[
                Step(
                    id="s1",
                    tool_name="mock_tool",
                    input_data={},
                    max_retries=2,
                    priority=TaskPriority.MEDIUM,
                ),
            ],
        )

        orchestrator = Orchestrator(
            registry=registry,
            config=MockConfig()
        )

        result = orchestrator.execute(plan)

        assert result.steps[0].retries == 2
        assert result.steps[0].status == StepStatus.FAILED
```

---

## Project Structure

```text
agent-harness/
│
├── README.md                      ← This file
├── PRD.md                         ← Product Requirements Document
├── pyproject.toml                 ← Project metadata and dependencies
├── config.yaml                    ← Default configuration
├── .env.example                   ← Environment variable template
├── .gitignore
├── LICENSE
│
├── agent_harness/                 ← Main package
│   ├── __init__.py                ← Public API exports
│   ├── __main__.py                ← CLI entry point
│   ├── harness.py                 ← AgentHarness class
│   │
│   ├── planning/
│   │   ├── __init__.py
│   │   ├── planner.py             ← LLM task decomposition
│   │   └── prompts.py             ← Prompt templates
│   │
│   ├── orchestration/
│   │   ├── __init__.py
│   │   ├── orchestrator.py        ← Core execution loop
│   │   ├── dependency.py          ← DAG / topological sort
│   │   └── recovery.py            ← Retry, fallback, re-plan
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py                ← BaseTool, ToolResult, ToolRegistry
│   │   ├── web_search.py
│   │   ├── web_scrape.py
│   │   ├── code_execute.py
│   │   ├── file_read.py
│   │   ├── file_write.py
│   │   ├── llm_extract.py
│   │   ├── llm_synthesize.py
│   │   ├── pdf_export.py
│   │   ├── csv_process.py
│   │   └── shell_command.py
│   │
│   ├── context/
│   │   ├── __init__.py
│   │   └── store.py
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── loader.py
│   │   └── schema.py
│   │
│   ├── logging/
│   │   ├── __init__.py
│   │   ├── logger.py
│   │   └── report.py
│   │
│   └── plugins/
│       ├── __init__.py
│       └── loader.py
│
├── plugins/                       ← User custom tools directory
│   ├── example_hello.py
│   └── example_database.py
│
├── tests/
│   ├── conftest.py
│   ├── test_planner.py
│   ├── test_orchestrator.py
│   ├── test_recovery.py
│   ├── test_context.py
│   ├── test_config.py
│   ├── test_plugin_loader.py
│   ├── test_tools/
│   │   ├── test_web_search.py
│   │   ├── test_code_execute.py
│   │   └── test_file_ops.py
│   └── integration/
│       ├── test_full_plan.py
│       └── test_recovery_e2e.py
│
├── examples/                      ← Example prompts and expected outputs
│   ├── research_report.py
│   ├── code_generation.py
│   └── data_analysis.py
│
├── output/                        ← Default output directory (gitignored)
├── logs/                          ← Log files (gitignored)
└── tmp/                           ← Temporary files (gitignored)
```

---

## Troubleshooting

### Common Issues

#### `OPENAI_API_KEY not set`

```bash
# Ensure .env file exists and contains your key
cat .env
# Should show: OPENAI_API_KEY=sk-...

# Or export directly
export OPENAI_API_KEY=sk-your-key-here
```

#### `ModuleNotFoundError: No module named 'agent_harness'`

```bash
# Ensure you installed in editable mode
pip install -e .

# Verify installation
python -c "import agent_harness; print('OK')"
```

#### `wkhtmltopdf not found` (PDF export fails)

```bash
# This is optional — install only if you need PDF export
# macOS: brew install wkhtmltopdf
# Ubuntu: sudo apt-get install wkhtmltopdf
# Or disable PDF tool and use markdown output instead
```

#### `Rate limit exceeded` (OpenAI API)

```yaml
# In config.yaml, use a cheaper/faster model for planning
llm:
  model: "gpt-4o-mini" # Cheaper, faster, sufficient for planning

# Or increase retry delays
execution:
  retry_base_delay: 5 # Longer backoff
```

#### Code execution hangs

```yaml
# Reduce code timeout
security:
  code_timeout: 15 # Kill after 15 seconds
```

#### Agent produces too many steps

```yaml
# Reduce max steps
execution:
  max_steps: 10
```

### Debug Mode

```bash
# Maximum verbosity
python -m agent_harness "Your task" --log-level DEBUG

# Check the log file for full execution trace
cat logs/agent_harness.log | python -m json.tool
```

### Getting Help

1. Check the logs: `./logs/agent_harness.log`
2. Run with `--dry-run` to inspect the plan without executing
3. Run with `--log-level DEBUG` for maximum detail
4. Open an issue on GitHub with the log output and your config (redact API keys)

---

## Contributing

### Development Setup

```bash
git clone https://github.com/yourusername/agent-harness.git
cd agent-harness

python -m venv venv
source venv/bin/activate

pip install -e ".[dev]"
```

### Code Standards

- **Formatter/Linter:** `ruff` (configured in `pyproject.toml`)
- **Type Checking:** `mypy --strict`
- **Tests:** `pytest` with >80% coverage target
- **Docstrings:** Google style
- **Commits:** Conventional commits (`feat:`, `fix:`, `docs:`, `test:`)

```bash
# Lint
ruff check agent_harness/

# Format
ruff format agent_harness/

# Type check
mypy agent_harness/

# Test
pytest --cov=agent_harness
```

### Adding a New Built-in Tool

1. Create `agent_harness/tools/your_tool.py`
2. Implement `BaseTool` interface (see [Writing Custom Tools](#writing-custom-tools))
3. Register in `agent_harness/tools/__init__.py`
4. Add to the default tool list in `harness.py`
5. Write tests in `tests/test_tools/test_your_tool.py`
6. Update the Built-in Tools table in this README
7. Update the planning prompt to include the tool description

### Pull Request Checklist

- [ ] All tests pass (`pytest`)
- [ ] No lint errors (`ruff check`)
- [ ] Type checks pass (`mypy`)
- [ ] New code has docstrings
- [ ] New features have tests
- [ ] README updated if user-facing changes
- [ ] Config schema updated if new config options

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Acknowledgments

- Architecture inspired by [Arena.ai](https://arena.ai) Agent Mode execution model
- Built on [OpenAI](https://openai.com) API for LLM capabilities
- Web search powered by [DuckDuckGo Search](https://github.com/deedy5/duckduckgo_search)
- Console output styled with [Rich](https://github.com/Textualize/rich)
