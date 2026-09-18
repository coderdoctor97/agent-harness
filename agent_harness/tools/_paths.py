"""Path safety guard for file_read/file_write.

Spec: SPEC-002 §3.4/3.5 Safety rows + SPEC-006
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any


def _get_output_dir(config: Any) -> str | None:
    if config is None:
        return None
    try:
        # Duck-typed: config.execution.output_dir
        exec_cfg = None
        if isinstance(config, dict):
            exec_cfg = config.get("execution")
            if isinstance(exec_cfg, dict):
                return exec_cfg.get("output_dir")
            if exec_cfg is not None:
                return getattr(exec_cfg, "output_dir", None)
            return None
        exec_cfg = getattr(config, "execution", None)
        if exec_cfg is None:
            return None
        if isinstance(exec_cfg, dict):
            return exec_cfg.get("output_dir")
        return getattr(exec_cfg, "output_dir", None)
    except Exception:  # noqa: BLE001
        return None


def _resolve_roots(roots: list[str | Path]) -> list[Path]:
    out: list[Path] = []
    for r in roots:
        try:
            p = Path(str(r)).resolve()
            out.append(p)
        except Exception:  # noqa: BLE001, S112
            continue
    return out


def _get_allowed_read_roots(config: Any, context: dict[str, Any]) -> list[Path]:
    roots: list[str | Path] = []
    # Workspace roots: cwd + repo root (two levels up from this file)
    try:
        cwd_root = Path.cwd().resolve()
        roots.append(cwd_root)
    except Exception:  # noqa: BLE001, S110
        pass
    try:
        repo_root = Path(__file__).resolve().parents[2]
        if repo_root.exists():
            roots.append(repo_root)
    except Exception:  # noqa: BLE001, S110
        pass
    # System temp dir for tests and temp workflows
    try:
        roots.append(Path(tempfile.gettempdir()).resolve())
    except Exception:  # noqa: BLE001, S110
        pass
    out_dir = _get_output_dir(config)
    if out_dir:
        roots.append(out_dir)
    # Context allowed_read_paths
    ctx_read = context.get("allowed_read_paths") if isinstance(context, dict) else None
    if isinstance(ctx_read, (list, tuple)):
        for p in ctx_read:
            if isinstance(p, (str, Path)):
                roots.append(p)
    return _resolve_roots(roots)


def _get_allowed_write_roots(config: Any, context: dict[str, Any]) -> list[Path]:
    roots: list[str | Path] = []
    out_dir = _get_output_dir(config)
    if out_dir:
        roots.append(out_dir)
    # Context allowed_write_paths
    ctx_write = context.get("allowed_write_paths") if isinstance(context, dict) else None
    if isinstance(ctx_write, (list, tuple)):
        for p in ctx_write:
            if isinstance(p, (str, Path)):
                roots.append(p)
    return _resolve_roots(roots)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        return path.is_relative_to(root)
    except AttributeError:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
    except Exception:  # noqa: BLE001
        return False


def is_path_allowed(
    target: str | Path,
    config: Any,
    context: dict[str, Any] | None,
    mode: str = "read",
) -> tuple[bool, str]:
    """Check if target path is inside allowed roots.

    Returns (allowed, reason). Reason is empty if allowed, else explains violation
    and enumerates allowed roots for error surfacing.
    """
    ctx: dict[str, Any] = context if isinstance(context, dict) else {}
    try:
        target_path = Path(str(target)).resolve()
    except Exception as exc:  # noqa: BLE001
        return False, f"Invalid path {target!r}: {exc}"

    if mode == "write":
        allowed_roots = _get_allowed_write_roots(config, ctx)
    else:
        allowed_roots = _get_allowed_read_roots(config, ctx)

    if not allowed_roots:
        return False, f"Path {target_path} is not inside allowed directories: (no allowed roots configured)"

    for root in allowed_roots:
        if target_path == root or _is_relative_to(target_path, root):
            return True, ""

    roots_str = ", ".join(str(r) for r in allowed_roots)
    return False, f"Path {target_path} is not inside allowed directories: {roots_str}"
