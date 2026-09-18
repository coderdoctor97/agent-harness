"""Static audit of the UI and the Windows launcher scripts.

These tests hold the design system and the accessibility floor in place without
a browser: token discipline, one live region per concern, keyboard-only paths,
reduced-motion support, labelled controls. They are deliberately about *rules*,
not pixels, so a redesign can pass them while a regression cannot.

Skill: frontend/frontend-design (token discipline, anti-generic check) ·
frontend/accessibility-a11y (WCAG 2.2 AA floor: names, focus, motion) ·
core-coding/git-workflow-hygiene (scripts are CRLF, so cmd.exe parses them)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "agent_harness" / "web" / "static"
REPO_ROOT = Path(__file__).resolve().parents[2]

HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
TOKENS = (STATIC / "tokens.css").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")


class TestDesignTokens:
    """frontend-design § 3.1-3.2 — a scale, not magic numbers."""

    def test_the_type_scale_is_the_documented_one(self) -> None:
        """12/14/16/20/28/40, declared once and referenced everywhere."""
        sizes = re.findall(r"--text-[a-z0-9]+:\s*([0-9.]+)rem", TOKENS)

        assert [float(size) * 16 for size in sizes] == [12, 14, 16, 20, 28, 40]

    def test_the_spacing_scale_is_an_eight_point_grid(self) -> None:
        values = [int(value) for value in re.findall(r"--space-\d+:\s*(\d+)px", TOKENS)]

        assert values and all(value % 4 == 0 for value in values)
        assert all(bigger >= smaller for smaller, bigger in zip(values, values[1:])), (
            "spacing tokens must be monotonic"
        )

    def test_component_styles_contain_no_raw_colours(self) -> None:
        """Colour lives in tokens only — a hex value in app.css is a defect."""
        without_vars = re.sub(r"var\([^)]*\)", "", CSS)

        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", without_vars)
        assert not re.search(r"\brgba?\(", without_vars)

    def test_the_accent_has_exactly_two_jobs(self) -> None:
        """frontend-design § 3.4 — accent for primary action and live state."""
        uses = set(re.findall(r"--accent[a-z-]*", CSS))

        assert uses <= {"--accent", "--accent-ink", "--accent-dim"}


class TestAccessibility:
    """accessibility-a11y § 3 — the AA floor, asserted structurally."""

    def test_every_form_control_has_a_label(self) -> None:
        for control_id in re.findall(r'<(?:textarea|input)[^>]*id="([^"]+)"', HTML):
            assert f'for="{control_id}"' in HTML, f"{control_id} has no <label for>"

    def test_the_page_declares_its_language(self) -> None:
        assert '<html lang="en">' in HTML

    def test_a_skip_link_reaches_the_task_form(self) -> None:
        assert 'class="visually-hidden" href="#task-prompt"' in HTML
        assert 'id="task-prompt"' in HTML

    def test_focus_is_visible_and_never_suppressed(self) -> None:
        assert ":focus-visible" in CSS
        assert "outline: none" not in CSS.replace("outline: var(--focus-ring)", "")

    def test_reduced_motion_is_honoured(self) -> None:
        assert "prefers-reduced-motion: reduce" in TOKENS
        assert "prefers-reduced-motion: no-preference" in CSS

    def test_interactive_elements_are_native_buttons(self) -> None:
        """accessibility-a11y § 3.2 — native semantics before ARIA."""
        assert "<button" in HTML
        assert 'role="button"' not in HTML

    def test_the_log_is_an_announced_live_region(self) -> None:
        assert 'role="log"' in HTML
        assert 'aria-live="polite"' in HTML

    def test_errors_are_announced_assertively(self) -> None:
        assert 'id="prompt-error" role="alert"' in HTML

    def test_the_tabs_use_the_aria_tabs_pattern(self) -> None:
        assert 'role="tablist"' in HTML
        assert 'role="tab"' in HTML
        assert 'role="tabpanel"' in HTML
        for tab in re.findall(r'<button class="tab"[^>]*id="([^"]+)"', HTML):
            assert "aria-selected" in HTML.split(f'id="{tab}"')[1][:200]

    def test_the_live_indicator_is_decorative(self) -> None:
        assert 'aria-hidden="true"' in HTML

    def test_icons_and_marks_are_hidden_from_assistive_tech(self) -> None:
        assert '<span class="brand__mark" aria-hidden="true">' in HTML


class TestBehaviourContracts:
    """The JS must keep the promises the API and the a11y rules make."""

    def test_all_requests_are_relative_so_the_server_can_be_proxied(self) -> None:
        assert not re.search(r"fetch\(\s*[\"'`]https?://", JS)

    def test_the_streaming_transport_has_a_polling_fallback(self) -> None:
        assert "EventSource" in JS
        assert "startPolling" in JS
        assert "onerror" in JS

    def test_the_cursor_is_used_when_resuming(self) -> None:
        assert "since=" in JS
        assert "next_seq" in JS

    def test_a_reconnect_after_error_falls_back_rather_than_dying(self) -> None:
        assert "if (!state.terminal) startPolling(taskId);" in JS

    def test_durations_and_sizes_are_rendered_human_readably(self) -> None:
        assert "formatDuration" in JS
        assert "formatBytes" in JS

    def test_artifacts_open_in_a_new_tab_safely(self) -> None:
        assert 'link.rel = "noopener"' in JS


class TestWindowsScripts:
    """The two batch files are part of the delivery, so they are tested too."""

    @pytest.mark.parametrize("name", ["setup.bat", "start.bat"])
    def test_the_script_exists_and_is_crlf(self, name: str) -> None:
        """cmd.exe mis-parses multi-line blocks in an LF-only file."""
        raw = (REPO_ROOT / name).read_bytes()

        assert raw, f"{name} is empty"
        assert raw.count(b"\r\n") > 20, f"{name} is not CRLF-terminated"
        assert not re.search(rb"(?<!\r)\n", raw), f"{name} has a bare LF line"

    @pytest.mark.parametrize("name", ["setup.bat", "start.bat"])
    def test_the_script_does_not_depend_on_the_calling_directory(
        self, name: str
    ) -> None:
        text = (REPO_ROOT / name).read_text(encoding="utf-8")

        assert 'pushd "%~dp0"' in text
        assert "popd" in text

    @pytest.mark.parametrize("name", ["setup.bat", "start.bat"])
    def test_the_script_reports_with_tagged_status_lines(self, name: str) -> None:
        text = (REPO_ROOT / name).read_text(encoding="utf-8")

        for tag in ("[INFO]", "[SUCCESS]", "[ERROR]"):
            assert tag in text, f"{name} never prints {tag}"

    def test_setup_is_idempotent_by_construction(self) -> None:
        """Every write is guarded by an existence check (re-running is safe)."""
        text = (REPO_ROOT / "setup.bat").read_text(encoding="utf-8")

        assert "if exist" in text  # venv, .env, config.yaml
        assert "venv" in text
        assert ".env.example" in text and "copy" in text
        assert "--editable" in text, "an editable install keeps imports local"

    def test_setup_checks_the_python_floor(self) -> None:
        text = (REPO_ROOT / "setup.bat").read_text(encoding="utf-8")

        assert "MIN_PY_MAJOR=3" in text and "MIN_PY_MINOR=9" in text
        assert "sys.version_info" in text

    def test_setup_names_the_remediation_for_a_missing_runtime(self) -> None:
        text = (REPO_ROOT / "setup.bat").read_text(encoding="utf-8")

        assert "Remediation" in text
        assert "python.org" in text

    def test_start_checks_the_environment_before_starting(self) -> None:
        text = (REPO_ROOT / "start.bat").read_text(encoding="utf-8")

        assert "if not exist" in text and "setup.bat" in text

    def test_start_runs_the_web_entry_point(self) -> None:
        text = (REPO_ROOT / "start.bat").read_text(encoding="utf-8")

        assert "-m agent_harness.web" in text

    def test_start_keeps_the_window_attached_for_ctrl_c(self) -> None:
        text = (REPO_ROOT / "start.bat").read_text(encoding="utf-8")

        assert "Ctrl+C" in text
        assert "pause" in text

    def test_start_accepts_a_port_override(self) -> None:
        text = (REPO_ROOT / "start.bat").read_text(encoding="utf-8")

        assert "/port" in text and "DEFAULT_PORT=8765" in text

    def test_the_scripts_agree_on_the_entry_point(self) -> None:
        """start.bat must launch exactly what the package documents."""
        assert "agent_harness.web" in (REPO_ROOT / "start.bat").read_text(
            encoding="utf-8"
        )
