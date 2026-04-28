"""Python orchestrator entry point.

Phase 2: `--dry-run` only. Reads filesystem state, asks the scheduler what
to do next, and prints the intended action. No subprocess calls, no LLM
calls. See `docs/python_orchestrator.md` for the full design.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a script from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.lib.context import ProjectContext  # noqa: E402
from scripts.lib.orchestration.scheduler import pick_next  # noqa: E402
from scripts.lib.orchestration.state import RichState  # noqa: E402


def _format_action(action) -> str:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="Python driver for the multi-agent research loop.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the next intended action and exit. No subprocess calls.",
    )
    parser.add_argument(
        "--prefer-in-flight",
        action="store_true",
        help="Prefer ideas that already have at least one design over fresh ideas.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Project root (defaults to the repo root).",
    )
    args = parser.parse_args(argv)

    if not args.dry_run:
        parser.error(
            "Phase 2 only supports --dry-run. "
            "Subprocess execution lands in Phase 3 (see docs/python_orchestrator.md)."
        )

    ctx = ProjectContext.create(args.root)
    state = RichState.snapshot(ctx)
    action = pick_next(state, prefer_in_flight=args.prefer_in_flight)
    print(_format_action(action))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
