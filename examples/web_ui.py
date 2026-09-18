"""Start the local web UI, or drive it headlessly — Plan 6's worked example.

Run it:

    python examples/web_ui.py                  # serve the UI on http://localhost:8765
    python examples/web_ui.py --port 9000      # a different port
    python examples/web_ui.py --no-browser     # do not open a browser
    python examples/web_ui.py --probe          # print the routes and exit
    python examples/web_ui.py --task "..."     # run one task on the console

``--task`` runs a task through the very same :class:`TaskRunner` the browser
talks to, printing each progress event as it arrives. That is the useful part of
this example: it shows the UI is a *view* over the ordinary harness API, not a
second execution path — so anything the CLI does, the UI does, with the same
config, the same plugins and the same recovery behaviour.

Spec: PRD G8 (local web UI) · SPEC-005 § 1 (harness API) · SPEC-003 § 2.1 (hooks)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent_harness.config import Config  # noqa: E402
from agent_harness.web.runner import TaskRunner  # noqa: E402
from agent_harness.web.server import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_PORT,
    WebDependencyError,
    launch,
)


def _load_config(path: str | None) -> Config:
    """Load ``config.yaml`` when present, else the documented defaults."""
    if path:
        return Config.from_file(path)
    default = PROJECT_ROOT / "config.yaml"
    return Config.from_file(str(default)) if default.exists() else Config()


def _probe() -> int:
    """Print the route table derived from the OpenAPI document."""
    from agent_harness.web.app import create_app

    document = create_app(_load_config(None)).openapi()
    print(f"{document['info']['title']} {document['info']['version']}")
    for route, methods in sorted(document["paths"].items()):
        for method in sorted(methods):
            print(f"  {method.upper():6} {route}")
    return 0


def _run_task(prompt: str, config: Config) -> int:
    """Run one task against a real harness and narrate the progress events."""
    harness_factory = None
    runner = TaskRunner(config, harness_factory=harness_factory)
    task = runner.submit(prompt)
    print(f"[INFO] task {task.id} submitted: {prompt}")

    seen = 0
    while True:
        events, seen = runner.events_since(task.id, seen)
        for event in events:
            fields = " ".join(
                f"{key}={value}" for key, value in event["fields"].items()
            )
            print(f"  {event['at'][11:19]}  {event['event']:<15} {fields}".rstrip())
        current = runner.get(task.id)
        if current is not None and current.terminal:
            break
        time.sleep(0.1)

    runner.shutdown()
    assert current is not None
    tag = "[SUCCESS]" if current.status == "completed" else "[ERROR]"
    detail = f" status={current.status}"
    if current.error:
        detail += f" error={current.error}"
    print(f"{tag}{detail} files={current.files_created}")
    if current.final_output:
        print("-" * 72)
        print(str(current.final_output)[:2000])
    return 0 if current.status == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and either probe, run one task, or serve the UI."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--probe", action="store_true", help="list the API routes")
    parser.add_argument("--task", default=None, help="run one task, then exit")
    args = parser.parse_args(argv)

    config = _load_config(args.config)

    if args.probe:
        return _probe()
    if args.task:
        return _run_task(args.task, config)

    try:
        return launch(
            config=config,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )
    except WebDependencyError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        print('[HINT]  pip install "agent-harness[web]"', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
