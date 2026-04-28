from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.orchestration.runner import (
    SPAWN_PLACEHOLDER,
    ClaudeCodeRunner,
    CodexRunner,
    RunResult,
    _TemplateRunner,
    load_runner_config,
    register_runner,
    runner_for_role,
)


def test_claude_default_template_contains_placeholder() -> None:
    runner = ClaudeCodeRunner()
    cmd = runner.build_command("Read agents/Architect/prompt.md and act as the Architect.")
    assert cmd[0] == "claude"
    assert "Read agents/Architect/prompt.md and act as the Architect." in cmd
    assert SPAWN_PLACEHOLDER not in cmd


def test_codex_default_template_contains_placeholder() -> None:
    runner = CodexRunner()
    cmd = runner.build_command("Read agents/Designer/prompt.md and act as the Designer.")
    assert cmd[0] == "codex"
    assert "Read agents/Designer/prompt.md and act as the Designer." in cmd


def test_template_must_contain_spawn_placeholder() -> None:
    with pytest.raises(ValueError, match="spawn_message"):
        ClaudeCodeRunner({"command_template": ["claude", "-p", "static"]})


def test_template_override_via_config() -> None:
    runner = ClaudeCodeRunner(
        {"command_template": ["claude", "--output-format", "stream-json", SPAWN_PLACEHOLDER]}
    )
    cmd = runner.build_command("hi")
    assert cmd == ["claude", "--output-format", "stream-json", "hi"]


def test_parity_same_message_same_position() -> None:
    """Both runners must put the spawn message into argv intact, so a Reviewer
    spawn message routed through either backend addresses the same agent."""
    msg = "Read agents/Reviewer/prompt.md and act as the Reviewer for idea_id=idea042. Mode: design review."
    claude_cmd = ClaudeCodeRunner().build_command(msg)
    codex_cmd = CodexRunner().build_command(msg)
    assert msg in claude_cmd
    assert msg in codex_cmd


def test_load_runner_config_missing_file(tmp_path: Path) -> None:
    assert load_runner_config(tmp_path) == {}


def test_load_runner_config_no_block(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(json.dumps({"results": {}}), encoding="utf-8")
    assert load_runner_config(tmp_path) == {}


def test_load_runner_config_returns_block(tmp_path: Path) -> None:
    block = {"default": "codex", "per_role": {"Reviewer": "claude-code"}}
    (tmp_path / ".automation.json").write_text(
        json.dumps({"agent_runner": block}), encoding="utf-8"
    )
    assert load_runner_config(tmp_path) == block


def test_runner_for_role_per_role_override(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        json.dumps(
            {
                "agent_runner": {
                    "default": "claude-code",
                    "per_role": {"Reviewer": "codex"},
                }
            }
        ),
        encoding="utf-8",
    )
    with patch("shutil.which", return_value="/usr/bin/dummy"):
        designer_runner = runner_for_role("Designer", tmp_path)
        reviewer_runner = runner_for_role("Reviewer", tmp_path)
    assert designer_runner.name == "claude-code"
    assert reviewer_runner.name == "codex"


def test_runner_for_role_unknown_name_raises(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        json.dumps({"agent_runner": {"default": "made-up-cli"}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown runner"):
        runner_for_role("Architect", tmp_path)


def test_runner_for_role_missing_command_raises(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        json.dumps({"agent_runner": {"default": "claude-code"}}),
        encoding="utf-8",
    )
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="not on PATH"):
            runner_for_role("Architect", tmp_path)


def test_run_missing_prompt_file_raises(tmp_path: Path) -> None:
    runner = ClaudeCodeRunner()
    with pytest.raises(FileNotFoundError):
        runner.run(
            prompt_file=tmp_path / "nope.md",
            spawn_message="hi",
            cwd=tmp_path,
            timeout_s=5,
        )


def test_run_captures_subprocess_result(tmp_path: Path) -> None:
    prompt = tmp_path / "p.md"
    prompt.write_text("# stub", encoding="utf-8")
    fake_completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="ok\n", stderr=""
    )
    runner = ClaudeCodeRunner()
    with patch("subprocess.run", return_value=fake_completed) as mock_run:
        result = runner.run(
            prompt_file=prompt, spawn_message="hi", cwd=tmp_path, timeout_s=5
        )
    assert mock_run.call_count == 1
    argv = mock_run.call_args.args[0]
    assert "hi" in argv
    assert result.ok
    assert result.exit_code == 0


def test_run_handles_timeout(tmp_path: Path) -> None:
    prompt = tmp_path / "p.md"
    prompt.write_text("# stub", encoding="utf-8")
    runner = ClaudeCodeRunner()
    err = subprocess.TimeoutExpired(cmd=["claude"], timeout=1, output="", stderr="")
    with patch("subprocess.run", side_effect=err):
        result = runner.run(
            prompt_file=prompt, spawn_message="hi", cwd=tmp_path, timeout_s=1
        )
    assert result.timed_out
    assert not result.ok


def test_third_party_runner_can_register() -> None:
    class Aider(_TemplateRunner):
        name = "aider"
        default_template = ("aider", SPAWN_PLACEHOLDER)

    register_runner(Aider)
    runner = Aider()
    assert runner.build_command("x") == ["aider", "x"]
