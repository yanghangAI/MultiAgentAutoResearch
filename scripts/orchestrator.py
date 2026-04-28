"""Python orchestrator entry point.

- `--dry-run`  : snapshot state, decide next action, print, exit.
- `--once`     : do --dry-run *and* execute the chosen action through the
                 configured agent runner (or `cli.py submit-implemented`
                 for a Submit action). Exits after one transition.

The driver-owned Builder retry loop (submit-test → poll → respawn) lands
in a follow-up commit; for now `--once` spawns Builder exactly once and
lets the user re-run the orchestrator to advance to the test step.

See `docs/python_orchestrator.md` and `docs/agent_runner_contract.md`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Allow running as a script from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.lib.context import ProjectContext  # noqa: E402
from scripts.lib.orchestration.builder_loop import (  # noqa: E402
    BuilderLoopConfig,
    _AuditLogger,
    run_builder_loop,
)
from scripts.lib.orchestration.runner import (  # noqa: E402
    AgentRunner,
    RunResult,
    runner_for_role,
    validate_all_runners,
)
from scripts.lib.orchestration.scheduler import pick_next  # noqa: E402
from scripts.lib.orchestration.state import RichState  # noqa: E402
from scripts.lib.orchestration.transitions import Action  # noqa: E402


_PROMPT_FILES: dict[str, tuple[str, ...]] = {
    "Architect": ("agents/Architect/prompt.md",),
    "Designer": ("agents/Designer/prompt.md",),
    "Reviewer": ("agents/Reviewer/prompt.md",),
    "Builder": ("agents/Builder/prompt.md",),
}

_LOG_TAIL_LIMIT = 4 * 1024


def _format_action(action: Action) -> str:
    lines = [
        f"Next action: {action.role}",
        f"  reason: {action.reason}",
    ]
    if action.idea_id:
        lines.append(f"  idea_id: {action.idea_id}")
    if action.design_id:
        lines.append(f"  design_id: {action.design_id}")
    if action.review_mode:
        lines.append(f"  review_mode: {action.review_mode}")
    if action.spawn_message:
        lines.append(f"  spawn_message: {action.spawn_message}")
    return "\n".join(lines)


def _resolve_prompt_file(action: Action, ctx: ProjectContext) -> Path:
    candidates = _PROMPT_FILES.get(action.role, ())
    for rel in candidates:
        candidate = ctx.root / rel
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"no prompt file found for role {action.role!r} under {ctx.root}"
    )


def _execute_submit(ctx: ProjectContext) -> int:
    """Run `cli.py submit-implemented` from the project root."""
    argv = [sys.executable, "scripts/cli.py", "submit-implemented"]
    print(f"$ {' '.join(argv)}")
    proc = subprocess.run(argv, cwd=str(ctx.root), check=False)
    return proc.returncode


def _execute_via_runner(
    action: Action,
    ctx: ProjectContext,
    runner: AgentRunner,
    timeout_s: int,
    session_id: str,
) -> RunResult:
    prompt_file = _resolve_prompt_file(action, ctx)
    print(f"$ runner={runner.name} command={runner.build_command(action.spawn_message)}")
    result = runner.run(
        prompt_file=prompt_file,
        spawn_message=action.spawn_message,
        cwd=ctx.root,
        timeout_s=timeout_s,
    )
    _append_audit_log(ctx, action, runner.name, result, session_id)
    return result


def _append_audit_log(
    ctx: ProjectContext,
    action: Action,
    runner_name: str,
    result: RunResult,
    session_id: str,
) -> None:
    log_dir = ctx.root / "logs" / "orchestrator"
    log_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_id": session_id,
        "role": action.role,
        "idea_id": action.idea_id,
        "design_id": action.design_id,
        "review_mode": action.review_mode,
        "runner": runner_name,
        "spawn_message": action.spawn_message,
        "exit_code": result.exit_code,
        "elapsed_s": round(result.elapsed_s, 2),
        "timed_out": result.timed_out,
        "stdout_tail": result.stdout_tail[-_LOG_TAIL_LIMIT:],
        "stderr_tail": result.stderr_tail[-_LOG_TAIL_LIMIT:],
    }
    log_path = log_dir / f"{time.strftime('%Y%m%d')}.jsonl"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="Python driver for the multi-agent research loop.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the next intended action and exit. No subprocess calls.",
    )
    mode.add_argument(
        "--once",
        action="store_true",
        help="Execute one transition end-to-end through the configured runner.",
    )
    parser.add_argument(
        "--prefer-in-flight",
        action="store_true",
        help="Prefer ideas that already have at least one approved design review.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Project root (defaults to the repo root).",
    )
    parser.add_argument(
        "--timeout-s",
        type=int,
        default=60 * 30,
        help="Per-invocation wall-clock timeout for sub-agent runs (default: 30 min).",
    )
    args = parser.parse_args(argv)

    ctx = ProjectContext.create(args.root)

    # Validate every configured runner up front (fail-loud at startup, even
    # for runners this invocation will not actually use). Only relevant in
    # --once mode; --dry-run does not invoke any runner.
    if args.once:
        validate_all_runners(ctx.root)

    state = RichState.snapshot(ctx)
    action = pick_next(state, prefer_in_flight=args.prefer_in_flight)
    print(_format_action(action))

    if args.dry_run:
        return 0

    # --once: execute the action.
    if action.role == "Submit":
        return _execute_submit(ctx)

    session_id = uuid.uuid4().hex
    print(f"  session_id={session_id}")
    runner = runner_for_role(action.role, ctx.root)

    if action.role == "Builder":
        loop_cfg = BuilderLoopConfig.load(ctx.root)
        log_path = ctx.root / "logs" / "orchestrator" / f"{time.strftime('%Y%m%d')}.jsonl"
        audit = _AuditLogger(log_path)
        loop_result = run_builder_loop(
            action=action,
            ctx=ctx,
            runner=runner,
            cfg=loop_cfg,
            parent_session_id=session_id,
            timeout_s=args.timeout_s,
            audit_log=audit,
        )
        print(
            f"  builder_loop attempts={loop_result.attempts} "
            f"outcome={loop_result.last_outcome.value if loop_result.last_outcome else 'none'} "
            f"dispatched_ok={loop_result.dispatched_ok} "
            f"notes={loop_result.notes!r}"
        )
        # Exit code semantics:
        #   0 = the driver dispatched cleanly (Builder ran, retries were
        #       enforced, terminal state — pass / implement_failed.md /
        #       budget exhaustion — is on disk).
        #   1 = driver-side failure (CLI crashed, timeout, etc.)
        return 0 if loop_result.dispatched_ok else 1

    # Non-Builder roles: single dispatch, single audit record.
    result = _execute_via_runner(action, ctx, runner, args.timeout_s, session_id)
    print(
        f"  exit_code={result.exit_code} "
        f"elapsed={result.elapsed_s:.1f}s "
        f"timed_out={result.timed_out}"
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
