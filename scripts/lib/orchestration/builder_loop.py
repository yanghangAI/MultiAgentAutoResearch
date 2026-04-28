"""Driver-owned Builder retry loop (Phase 3b).

Builder agents implement a single design and exit. The orchestrator drives
the surrounding loop:

    spawn Builder
       └─> on exit, if implement_failed.md → done (Builder gave up)
       └─> else run cli.py submit-test
              └─> poll until pass / fail / timeout
                     ├─ PASS → done, design ready for code review
                     ├─ FAIL → respawn Builder with the failure log
                     └─ TIMEOUT → respawn Builder with a timeout note
       └─> after `max_test_attempts` failed attempts, the driver writes
           implement_failed.md itself and stops.

Outcome detection is project-specific. The driver supports two modes:

  1. **Configured command** (`outcome_check_command` in `.automation.json`):
     a shell command run from the project root with `{root}` and
     `{design_dir}` placeholders. Exit-code contract:
        0 = PASS, 1 = FAIL, 2 = STILL_RUNNING, other = ERROR (treated as FAIL).
  2. **Built-in default** (when no command is configured):
        - <design_dir>/training_failed.txt present → FAIL
        - <design_dir>/test_output/metrics.csv has ≥2 lines → PASS
        - else → STILL_RUNNING

Failure logs are injected into the next spawn message inline if they fit
under `failure_log.max_inline_bytes`; otherwise they are spilled to
`<design_dir>/last_failure.log` and the spawn message references the
path. This is the documented "minimal spawn message" exception (alongside
Debugger).
"""

from __future__ import annotations

import enum
import json
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from scripts.lib.context import ProjectContext
from scripts.lib.orchestration.runner import AgentRunner, RunResult
from scripts.lib.orchestration.transitions import Action


class Outcome(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    STILL_RUNNING = "STILL_RUNNING"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


@dataclass(frozen=True)
class BuilderLoopConfig:
    max_test_attempts: int = 10
    max_code_review_rejections: int = 3  # consumed by future code-review loop
    poll_interval_s: int = 30
    test_timeout_s: int = 1800
    outcome_check_command: str | None = None
    failure_log_max_inline_bytes: int = 4096

    @staticmethod
    def load(root: Path) -> "BuilderLoopConfig":
        cfg_path = root / ".automation.json"
        if not cfg_path.is_file():
            return BuilderLoopConfig()
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return BuilderLoopConfig()
        block = data.get("builder_loop") or {}
        if not isinstance(block, dict):
            return BuilderLoopConfig()
        defaults = BuilderLoopConfig()
        return BuilderLoopConfig(
            max_test_attempts=int(block.get("max_test_attempts", defaults.max_test_attempts)),
            max_code_review_rejections=int(
                block.get("max_code_review_rejections", defaults.max_code_review_rejections)
            ),
            poll_interval_s=int(block.get("poll_interval_s", defaults.poll_interval_s)),
            test_timeout_s=int(block.get("test_timeout_s", defaults.test_timeout_s)),
            outcome_check_command=block.get("outcome_check_command") or None,
            failure_log_max_inline_bytes=int(
                block.get("failure_log_max_inline_bytes", defaults.failure_log_max_inline_bytes)
            ),
        )


@dataclass(frozen=True)
class LoopResult:
    """Driver-side outcome of one Builder loop run.

    `dispatched_ok` is True iff the driver completed its dispatch; the
    *agent's* pass/fail still lives on disk (implementation_summary.md /
    implement_failed.md / test artifacts) and is read by the next snapshot.
    """

    dispatched_ok: bool
    attempts: int
    last_outcome: Outcome | None
    last_run_result: RunResult | None
    notes: str = ""


def run_builder_loop(
    *,
    action: Action,
    ctx: ProjectContext,
    runner: AgentRunner,
    cfg: BuilderLoopConfig,
    parent_session_id: str,
    timeout_s: int,
    audit_log: "_AuditLogger | None" = None,
    sleep: callable = time.sleep,
) -> LoopResult:
    if action.role != "Builder":
        raise ValueError(f"run_builder_loop expected role=Builder, got {action.role!r}")
    if action.idea_id is None or action.design_id is None:
        raise ValueError("Builder action must carry idea_id and design_id")

    design_dir = ctx.root / "runs" / action.idea_id / action.design_id
    base_message = action.spawn_message
    last_run_result: RunResult | None = None
    last_outcome: Outcome | None = None
    last_failure_text = ""

    for attempt in range(1, cfg.max_test_attempts + 1):
        attempt_session_id = f"{parent_session_id}.b{attempt}"
        spawn_message = (
            base_message
            if attempt == 1
            else _spawn_message_with_failure(
                base_message, last_failure_text, design_dir, cfg
            )
        )

        # 1. Spawn Builder.
        run_result = _spawn(
            runner=runner,
            ctx=ctx,
            spawn_message=spawn_message,
            timeout_s=timeout_s,
            attempt_session_id=attempt_session_id,
        )
        last_run_result = run_result
        if audit_log:
            audit_log.record(
                action=action,
                phase="builder",
                attempt=attempt,
                attempt_session_id=attempt_session_id,
                runner_name=runner.name,
                spawn_message=spawn_message,
                result=run_result,
            )
        if not run_result.ok:
            return LoopResult(
                dispatched_ok=False,
                attempts=attempt,
                last_outcome=None,
                last_run_result=run_result,
                notes=f"Builder runner failed on attempt {attempt}",
            )

        # 2. Builder may have given up cleanly.
        if (design_dir / "implement_failed.md").is_file():
            return LoopResult(
                dispatched_ok=True,
                attempts=attempt,
                last_outcome=None,
                last_run_result=run_result,
                notes="Builder wrote implement_failed.md",
            )

        # 3. Submit the sanity test.
        submit_result = _run_submit_test(ctx, design_dir, attempt_session_id, audit_log, action)
        if submit_result.returncode != 0:
            last_failure_text = (
                f"submit-test failed (exit {submit_result.returncode}):\n"
                f"{submit_result.stdout}\n{submit_result.stderr}"
            )
            last_outcome = Outcome.FAIL
            continue

        # 4. Poll for outcome.
        outcome, evidence = poll_for_outcome(design_dir, cfg, sleep=sleep)
        last_outcome = outcome
        if audit_log:
            audit_log.record_outcome(
                action=action,
                attempt=attempt,
                attempt_session_id=attempt_session_id,
                outcome=outcome,
                evidence=evidence,
            )

        if outcome == Outcome.PASS:
            return LoopResult(
                dispatched_ok=True,
                attempts=attempt,
                last_outcome=outcome,
                last_run_result=run_result,
                notes="passed sanity test",
            )

        # 5. Otherwise prepare retry: collect failure text from disk.
        last_failure_text = _collect_failure_text(design_dir, outcome, evidence)

    # Exhausted retry budget.
    _write_implement_failed(
        design_dir,
        f"Driver gave up after {cfg.max_test_attempts} test attempts. "
        f"Last outcome: {last_outcome.value if last_outcome else 'unknown'}.",
    )
    return LoopResult(
        dispatched_ok=True,
        attempts=cfg.max_test_attempts,
        last_outcome=last_outcome,
        last_run_result=last_run_result,
        notes="exhausted retry budget; wrote implement_failed.md",
    )


def poll_for_outcome(
    design_dir: Path,
    cfg: BuilderLoopConfig,
    *,
    sleep: callable = time.sleep,
) -> tuple[Outcome, str]:
    """Poll until outcome is non-running or timeout. Returns (outcome, evidence)."""
    start = time.monotonic()
    while True:
        outcome, evidence = check_outcome(design_dir, cfg)
        if outcome != Outcome.STILL_RUNNING:
            return outcome, evidence
        if time.monotonic() - start > cfg.test_timeout_s:
            return Outcome.TIMEOUT, f"polled for >{cfg.test_timeout_s}s without conclusion"
        sleep(cfg.poll_interval_s)


def check_outcome(design_dir: Path, cfg: BuilderLoopConfig) -> tuple[Outcome, str]:
    """Return one (outcome, evidence) tuple. No polling; caller handles retry."""
    if cfg.outcome_check_command:
        return _check_outcome_via_command(design_dir, cfg.outcome_check_command)
    return _check_outcome_default(design_dir)


def _check_outcome_via_command(
    design_dir: Path, template: str
) -> tuple[Outcome, str]:
    cmd = template.format(root=str(design_dir.parents[2]), design_dir=str(design_dir))
    try:
        proc = subprocess.run(
            shlex.split(cmd),
            cwd=str(design_dir.parents[2]),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Outcome.ERROR, "outcome_check_command timed out (60s)"
    except OSError as exc:
        return Outcome.ERROR, f"outcome_check_command exec failed: {exc}"
    code_to_outcome = {0: Outcome.PASS, 1: Outcome.FAIL, 2: Outcome.STILL_RUNNING}
    outcome = code_to_outcome.get(proc.returncode, Outcome.ERROR)
    evidence = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if not evidence:
        evidence = f"exit {proc.returncode}"
    return outcome, evidence


def _check_outcome_default(design_dir: Path) -> tuple[Outcome, str]:
    if (design_dir / "training_failed.txt").is_file():
        return Outcome.FAIL, "training_failed.txt present"
    metrics = design_dir / "test_output" / "metrics.csv"
    if metrics.is_file():
        try:
            with metrics.open("r", encoding="utf-8") as handle:
                lines = sum(1 for _ in handle)
        except OSError:
            return Outcome.STILL_RUNNING, "metrics.csv unreadable"
        if lines >= 2:
            return Outcome.PASS, f"metrics.csv has {lines} lines"
    return Outcome.STILL_RUNNING, "no terminal signal yet"


def _spawn_message_with_failure(
    base_message: str,
    failure_text: str,
    design_dir: Path,
    cfg: BuilderLoopConfig,
) -> str:
    """Inject a failure log into the spawn message.

    Inline if it fits under the configured limit, else spill to
    <design_dir>/last_failure.log and reference the path.
    """
    if not failure_text.strip():
        return base_message
    encoded = failure_text.encode("utf-8", errors="replace")
    if len(encoded) <= cfg.failure_log_max_inline_bytes:
        return (
            f"{base_message}\n\n"
            f"Failure log from prior attempt:\n{failure_text.rstrip()}"
        )
    spill_path = design_dir / "last_failure.log"
    try:
        spill_path.write_text(failure_text, encoding="utf-8")
    except OSError:
        # Couldn't spill — truncate inline as a last resort.
        truncated = encoded[: cfg.failure_log_max_inline_bytes].decode(
            "utf-8", errors="replace"
        )
        return (
            f"{base_message}\n\n"
            f"Failure log (truncated to {cfg.failure_log_max_inline_bytes} bytes):\n"
            f"{truncated}"
        )
    rel = spill_path.relative_to(design_dir.parents[2])
    return (
        f"{base_message}\n\n"
        f"Failure log from prior attempt is in: {rel} "
        f"(too large to inline)."
    )


def _spawn(
    *,
    runner: AgentRunner,
    ctx: ProjectContext,
    spawn_message: str,
    timeout_s: int,
    attempt_session_id: str,
) -> RunResult:
    prompt_file = ctx.root / "agents" / "Builder" / "prompt.md"
    log_dir = ctx.root / "logs" / "orchestrator" / "sessions"
    log_dir.mkdir(parents=True, exist_ok=True)
    return runner.run(
        prompt_file=prompt_file,
        spawn_message=spawn_message,
        cwd=ctx.root,
        timeout_s=timeout_s,
        stdout_path=log_dir / f"{attempt_session_id}.stdout",
        stderr_path=log_dir / f"{attempt_session_id}.stderr",
    )


def _run_submit_test(
    ctx: ProjectContext,
    design_dir: Path,
    attempt_session_id: str,
    audit_log: "_AuditLogger | None",
    action: Action,
) -> subprocess.CompletedProcess:
    import sys

    argv = [sys.executable, "scripts/cli.py", "submit-test", str(design_dir)]
    proc = subprocess.run(
        argv, cwd=str(ctx.root), capture_output=True, text=True, check=False
    )
    if audit_log:
        audit_log.record_submit_test(
            action=action,
            attempt_session_id=attempt_session_id,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    return proc


def _collect_failure_text(
    design_dir: Path, outcome: Outcome, evidence: str
) -> str:
    pieces = [f"Outcome: {outcome.value}", f"Evidence: {evidence}"]
    failed = design_dir / "training_failed.txt"
    if failed.is_file():
        try:
            pieces.append("training_failed.txt:\n" + failed.read_text(encoding="utf-8"))
        except OSError:
            pass
    test_log = design_dir / "test_output" / "test.log"
    if test_log.is_file():
        try:
            with test_log.open("rb") as handle:
                size = handle.seek(0, 2)
                handle.seek(max(0, size - 4096))
                tail = handle.read().decode("utf-8", errors="replace")
            pieces.append(f"test.log tail:\n{tail}")
        except OSError:
            pass
    return "\n\n".join(pieces)


def _write_implement_failed(design_dir: Path, message: str) -> None:
    target = design_dir / "implement_failed.md"
    if target.is_file() and target.read_text(encoding="utf-8").strip():
        return  # Builder already wrote one; do not clobber
    target.write_text(message + "\n", encoding="utf-8")


class _AuditLogger:
    """Optional per-invocation audit recorder. The orchestrator entry
    point creates one and passes it in; tests can pass None to skip
    logging."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        action: Action,
        phase: str,
        attempt: int,
        attempt_session_id: str,
        runner_name: str,
        spawn_message: str,
        result: RunResult,
    ) -> None:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "phase": phase,
            "attempt": attempt,
            "attempt_session_id": attempt_session_id,
            "role": action.role,
            "idea_id": action.idea_id,
            "design_id": action.design_id,
            "runner": runner_name,
            "spawn_message_bytes": len(spawn_message.encode("utf-8")),
            "exit_code": result.exit_code,
            "elapsed_s": round(result.elapsed_s, 2),
            "timed_out": result.timed_out,
            "stdout_tail": result.stdout_tail,
            "stderr_tail": result.stderr_tail,
        }
        self._append(record)

    def record_submit_test(
        self,
        *,
        action: Action,
        attempt_session_id: str,
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        self._append(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "phase": "submit_test",
                "attempt_session_id": attempt_session_id,
                "role": action.role,
                "idea_id": action.idea_id,
                "design_id": action.design_id,
                "returncode": returncode,
                "stdout_tail": (stdout or "")[-2048:],
                "stderr_tail": (stderr or "")[-2048:],
            }
        )

    def record_outcome(
        self,
        *,
        action: Action,
        attempt: int,
        attempt_session_id: str,
        outcome: Outcome,
        evidence: str,
    ) -> None:
        self._append(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "phase": "outcome",
                "attempt": attempt,
                "attempt_session_id": attempt_session_id,
                "role": action.role,
                "idea_id": action.idea_id,
                "design_id": action.design_id,
                "outcome": outcome.value,
                "evidence": evidence,
            }
        )

    def _append(self, record: dict) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
