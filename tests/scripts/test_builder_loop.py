from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.context import ProjectContext
from scripts.lib.orchestration.builder_loop import (
    BuilderLoopConfig,
    LoopResult,
    Outcome,
    check_outcome,
    poll_for_outcome,
    run_builder_loop,
    _AuditLogger,
)
from scripts.lib.orchestration.runner import RunResult
from scripts.lib.orchestration.transitions import Action


# ---------- helpers ---------------------------------------------------------


def _make_project(tmp_path: Path, *, builder_loop_cfg: dict | None = None) -> ProjectContext:
    cfg: dict = {}
    if builder_loop_cfg is not None:
        cfg["builder_loop"] = builder_loop_cfg
    (tmp_path / ".automation.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "agents" / "Builder").mkdir(parents=True)
    (tmp_path / "agents" / "Builder" / "prompt.md").write_text("# stub", encoding="utf-8")
    (tmp_path / "runs" / "idea001" / "design001").mkdir(parents=True)
    (tmp_path / "runs" / "idea001" / "design001" / "design.md").write_text(
        "**Design Description:** stub\n", encoding="utf-8"
    )
    return ProjectContext.create(tmp_path)


def _builder_action() -> Action:
    return Action(
        role="Builder",
        idea_id="idea001",
        design_id="design001",
        review_mode=None,
        reason="stub",
        spawn_message=(
            "Read agents/Builder/prompt.md and act as the Builder "
            "for idea_id=idea001, design_id=design001."
        ),
    )


class FakeRunner:
    """A Runner stand-in that mutates the filesystem to simulate Builder.

    Each call invokes the next side_effect callable in order, which
    receives the spawn_message and is free to write/modify files in the
    design dir. Returns a fixed RunResult.
    """

    name = "fake"

    def __init__(self, side_effects: list, design_dir: Path) -> None:
        self._side_effects = list(side_effects)
        self._design_dir = design_dir
        self.calls: list[str] = []

    def run(self, *, prompt_file, spawn_message, cwd, timeout_s,
            stdout_path=None, stderr_path=None) -> RunResult:
        self.calls.append(spawn_message)
        if not self._side_effects:
            raise AssertionError("FakeRunner ran out of side effects")
        effect = self._side_effects.pop(0)
        effect(self._design_dir, spawn_message)
        return RunResult(exit_code=0, stdout_tail="", stderr_tail="", elapsed_s=0.01)


def _write(p: Path, text: str = "stub") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------- check_outcome / poll_for_outcome --------------------------------


def test_default_outcome_pass_when_metrics_csv_has_rows(tmp_path: Path) -> None:
    design_dir = tmp_path / "runs" / "idea001" / "design001"
    design_dir.mkdir(parents=True)
    (design_dir / "test_output").mkdir()
    (design_dir / "test_output" / "metrics.csv").write_text(
        "epoch,loss\n1,0.5\n", encoding="utf-8"
    )
    cfg = BuilderLoopConfig()
    outcome, _ = check_outcome(design_dir, cfg)
    assert outcome == Outcome.PASS


def test_default_outcome_fail_when_training_failed_present(tmp_path: Path) -> None:
    design_dir = tmp_path / "runs" / "idea001" / "design001"
    design_dir.mkdir(parents=True)
    (design_dir / "training_failed.txt").write_text("crashed", encoding="utf-8")
    outcome, _ = check_outcome(design_dir, BuilderLoopConfig())
    assert outcome == Outcome.FAIL


def test_default_outcome_still_running_when_no_signal(tmp_path: Path) -> None:
    design_dir = tmp_path / "runs" / "idea001" / "design001"
    design_dir.mkdir(parents=True)
    outcome, _ = check_outcome(design_dir, BuilderLoopConfig())
    assert outcome == Outcome.STILL_RUNNING


def test_outcome_check_command_exit_codes(tmp_path: Path) -> None:
    design_dir = tmp_path / "runs" / "idea001" / "design001"
    design_dir.mkdir(parents=True)
    cfg = BuilderLoopConfig(outcome_check_command="bash -c 'exit 1'")
    outcome, _ = check_outcome(design_dir, cfg)
    assert outcome == Outcome.FAIL


def test_poll_for_outcome_times_out(tmp_path: Path) -> None:
    design_dir = tmp_path / "runs" / "idea001" / "design001"
    design_dir.mkdir(parents=True)
    cfg = BuilderLoopConfig(poll_interval_s=0, test_timeout_s=0)
    sleeps: list[int] = []
    outcome, _ = poll_for_outcome(design_dir, cfg, sleep=sleeps.append)
    assert outcome == Outcome.TIMEOUT


# ---------- BuilderLoopConfig.load ------------------------------------------


def test_loop_config_defaults_when_missing(tmp_path: Path) -> None:
    cfg = BuilderLoopConfig.load(tmp_path)
    assert cfg.max_test_attempts == 10
    assert cfg.outcome_check_command is None


def test_loop_config_overrides(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        json.dumps(
            {
                "builder_loop": {
                    "max_test_attempts": 3,
                    "poll_interval_s": 5,
                    "outcome_check_command": "bash custom.sh {design_dir}",
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = BuilderLoopConfig.load(tmp_path)
    assert cfg.max_test_attempts == 3
    assert cfg.poll_interval_s == 5
    assert cfg.outcome_check_command == "bash custom.sh {design_dir}"


# ---------- run_builder_loop integration tests ------------------------------


def test_loop_pass_on_first_attempt(tmp_path: Path) -> None:
    ctx = _make_project(tmp_path)
    design_dir = ctx.root / "runs" / "idea001" / "design001"

    def builder_writes_pass(d: Path, _msg: str) -> None:
        _write(d / "implementation_summary.md", "done")
        _write(d / "test_output" / "metrics.csv", "epoch,loss\n1,0.5\n")

    runner = FakeRunner([builder_writes_pass], design_dir)
    cfg = BuilderLoopConfig(max_test_attempts=3, poll_interval_s=0, test_timeout_s=10)

    with patch(
        "scripts.lib.orchestration.builder_loop._run_submit_test"
    ) as fake_submit:
        fake_submit.return_value = type(
            "P", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )()
        result = run_builder_loop(
            action=_builder_action(),
            ctx=ctx,
            runner=runner,
            cfg=cfg,
            parent_session_id="sess1",
            timeout_s=60,
            sleep=lambda s: None,
        )

    assert result.dispatched_ok
    assert result.attempts == 1
    assert result.last_outcome == Outcome.PASS
    assert len(runner.calls) == 1


def test_loop_passes_on_second_attempt_after_failure(tmp_path: Path) -> None:
    ctx = _make_project(tmp_path)
    design_dir = ctx.root / "runs" / "idea001" / "design001"

    def builder_writes_fail(d: Path, _msg: str) -> None:
        _write(d / "implementation_summary.md", "v1")
        _write(d / "training_failed.txt", "v1 broke")

    def builder_writes_pass(d: Path, msg: str) -> None:
        # On retry, the spawn message must include the failure log.
        assert "Failure log" in msg, msg
        # Clear the prior fail signal, write success markers.
        (d / "training_failed.txt").unlink()
        _write(d / "implementation_summary.md", "v2")
        _write(d / "test_output" / "metrics.csv", "epoch,loss\n1,0.4\n")

    runner = FakeRunner([builder_writes_fail, builder_writes_pass], design_dir)
    cfg = BuilderLoopConfig(max_test_attempts=3, poll_interval_s=0, test_timeout_s=10)

    with patch("scripts.lib.orchestration.builder_loop._run_submit_test") as fake_submit:
        fake_submit.return_value = type(
            "P", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )()
        result = run_builder_loop(
            action=_builder_action(),
            ctx=ctx,
            runner=runner,
            cfg=cfg,
            parent_session_id="sess1",
            timeout_s=60,
            sleep=lambda s: None,
        )

    assert result.dispatched_ok
    assert result.attempts == 2
    assert result.last_outcome == Outcome.PASS


def test_loop_exhausts_budget_and_writes_implement_failed(tmp_path: Path) -> None:
    ctx = _make_project(tmp_path)
    design_dir = ctx.root / "runs" / "idea001" / "design001"

    def always_fails(d: Path, _msg: str) -> None:
        _write(d / "implementation_summary.md", "v")
        _write(d / "training_failed.txt", "boom")

    runner = FakeRunner([always_fails, always_fails], design_dir)
    cfg = BuilderLoopConfig(max_test_attempts=2, poll_interval_s=0, test_timeout_s=10)

    with patch("scripts.lib.orchestration.builder_loop._run_submit_test") as fake_submit:
        fake_submit.return_value = type(
            "P", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )()
        result = run_builder_loop(
            action=_builder_action(),
            ctx=ctx,
            runner=runner,
            cfg=cfg,
            parent_session_id="sess1",
            timeout_s=60,
            sleep=lambda s: None,
        )

    assert result.dispatched_ok
    assert result.attempts == 2
    impl_failed = (design_dir / "implement_failed.md").read_text()
    assert "gave up after 2 test attempts" in impl_failed


def test_loop_breaks_when_builder_writes_implement_failed(tmp_path: Path) -> None:
    ctx = _make_project(tmp_path)
    design_dir = ctx.root / "runs" / "idea001" / "design001"

    def builder_gives_up(d: Path, _msg: str) -> None:
        _write(d / "implement_failed.md", "Cannot solve.")

    runner = FakeRunner([builder_gives_up], design_dir)
    cfg = BuilderLoopConfig(max_test_attempts=5, poll_interval_s=0, test_timeout_s=10)

    with patch("scripts.lib.orchestration.builder_loop._run_submit_test") as fake_submit:
        fake_submit.return_value = type(
            "P", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )()
        result = run_builder_loop(
            action=_builder_action(),
            ctx=ctx,
            runner=runner,
            cfg=cfg,
            parent_session_id="sess1",
            timeout_s=60,
            sleep=lambda s: None,
        )

    assert result.dispatched_ok
    assert result.attempts == 1
    # Driver must NOT have clobbered Builder's own implement_failed.md
    assert "Cannot solve" in (design_dir / "implement_failed.md").read_text()
    # No submit-test should have run.
    assert fake_submit.call_count == 0


def test_loop_spills_large_failure_log_to_file(tmp_path: Path) -> None:
    ctx = _make_project(tmp_path)
    design_dir = ctx.root / "runs" / "idea001" / "design001"

    big_blob = "X" * 20_000

    def builder_fails_with_big_log(d: Path, _msg: str) -> None:
        _write(d / "implementation_summary.md", "v1")
        _write(d / "training_failed.txt", big_blob)

    captured_messages: list[str] = []

    def builder_pass(d: Path, msg: str) -> None:
        captured_messages.append(msg)
        (d / "training_failed.txt").unlink()
        _write(d / "test_output" / "metrics.csv", "e,l\n1,0.1\n")

    runner = FakeRunner([builder_fails_with_big_log, builder_pass], design_dir)
    cfg = BuilderLoopConfig(
        max_test_attempts=3,
        poll_interval_s=0,
        test_timeout_s=10,
        failure_log_max_inline_bytes=512,
    )

    with patch("scripts.lib.orchestration.builder_loop._run_submit_test") as fake_submit:
        fake_submit.return_value = type(
            "P", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )()
        result = run_builder_loop(
            action=_builder_action(),
            ctx=ctx,
            runner=runner,
            cfg=cfg,
            parent_session_id="sess1",
            timeout_s=60,
            sleep=lambda s: None,
        )

    assert result.dispatched_ok
    # The retry spawn message should reference the spill file path.
    retry_msg = captured_messages[0]
    assert "last_failure.log" in retry_msg
    assert "too large to inline" in retry_msg
    spill = design_dir / "last_failure.log"
    assert spill.is_file() and big_blob in spill.read_text()


def test_loop_records_audit_log_with_session_correlation(tmp_path: Path) -> None:
    ctx = _make_project(tmp_path)
    design_dir = ctx.root / "runs" / "idea001" / "design001"

    def builder_pass(d: Path, _msg: str) -> None:
        _write(d / "implementation_summary.md", "done")
        _write(d / "test_output" / "metrics.csv", "e,l\n1,0.1\n")

    runner = FakeRunner([builder_pass], design_dir)
    cfg = BuilderLoopConfig(max_test_attempts=3, poll_interval_s=0, test_timeout_s=10)

    log_path = ctx.root / "logs" / "orchestrator" / "audit.jsonl"
    audit = _AuditLogger(log_path)

    with patch("scripts.lib.orchestration.builder_loop._run_submit_test") as fake_submit:
        fake_submit.return_value = type(
            "P", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )()
        run_builder_loop(
            action=_builder_action(),
            ctx=ctx,
            runner=runner,
            cfg=cfg,
            parent_session_id="parent-abc",
            timeout_s=60,
            audit_log=audit,
            sleep=lambda s: None,
        )

    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    phases = [r["phase"] for r in records]
    assert "builder" in phases
    assert "outcome" in phases
    # Every record carries an attempt_session_id derived from parent.
    for r in records:
        if "attempt_session_id" in r:
            assert r["attempt_session_id"].startswith("parent-abc.")
