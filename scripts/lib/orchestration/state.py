"""Rich state snapshot for the Python orchestrator.

`RichState.snapshot(ctx)` reads the filesystem (CSVs and per-design review files)
and returns an immutable in-memory view of every idea and design. The driver
re-snapshots after every CLI script call and every sub-agent invocation; no
state is held across operations.

Why this exists: `cli.py sync-status` rebuilds tracker CSVs from the filesystem
and silently excludes designs without an APPROVED design review. Scheduling
retry vs. move-on decisions therefore needs the raw review-file contents, not
just the post-sync CSV rows. This module joins the two into one snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.lib import layout, store
from scripts.lib.context import ProjectContext
from scripts.lib.models import Status


@dataclass(frozen=True)
class DesignState:
    idea_id: str
    design_id: str
    description: str
    status: str  # post-sync-status value, may be empty if not yet registered
    design_path: Path
    has_design_md: bool
    design_review_text: str  # empty string if file missing
    code_review_text: str
    design_review_approved: bool  # computed at snapshot using cfg.approved_token
    code_review_approved: bool
    has_implementation_summary: bool
    has_implement_failed: bool
    has_scope_check_pass: bool
    has_scope_check_fail: bool
    has_job_submitted: bool
    has_training_failed: bool
    revision: str
    stale_since: str


@dataclass(frozen=True)
class IdeaState:
    idea_id: str
    idea_name: str
    status: str
    idea_md_path: Path
    expected_designs: int | None
    designs: tuple[DesignState, ...]


@dataclass(frozen=True)
class RichState:
    ctx: ProjectContext
    ideas: tuple[IdeaState, ...]

    @staticmethod
    def snapshot(ctx: ProjectContext) -> RichState:
        runs = layout.runs_dir(ctx.root)
        approved = ctx.cfg.status.approved_token

        # Pre-index post-sync CSVs so we can carry status / revision / stale_since.
        idea_csv_rows = {
            r.get("Idea_ID", ""): r
            for r in store.read_dict_rows(layout.idea_csv_path(ctx.root))
        }

        ideas: list[IdeaState] = []
        if not runs.is_dir():
            return RichState(ctx=ctx, ideas=())

        for idea_path in sorted(runs.glob("idea*")):
            if not idea_path.is_dir():
                continue
            idea_id = idea_path.name
            idea_md = layout.idea_md_path(idea_id, ctx.root)
            if not idea_md.exists():
                continue

            idea_row = idea_csv_rows.get(idea_id, {})
            idea_name = idea_row.get("Idea_Name", "") or _infer_idea_name(idea_md)
            idea_status = idea_row.get("Status", "") or ""
            expected = _parse_expected_designs(idea_md)

            design_csv_rows = {
                r.get("Design_ID", ""): r
                for r in store.read_dict_rows(layout.design_csv_path(idea_id, ctx.root))
            }

            designs: list[DesignState] = []
            for design_path in sorted(idea_path.glob("design*")):
                if not design_path.is_dir():
                    continue
                design_id = design_path.name
                row = design_csv_rows.get(design_id, {})
                design_review_text = store.read_text(design_path / "design_review.md")
                code_review_text = store.read_text(design_path / "code_review.md")
                designs.append(
                    DesignState(
                        idea_id=idea_id,
                        design_id=design_id,
                        description=row.get("Design_Description", ""),
                        status=row.get("Status", ""),
                        design_path=design_path,
                        has_design_md=(design_path / "design.md").exists(),
                        design_review_text=design_review_text,
                        code_review_text=code_review_text,
                        design_review_approved=(approved in design_review_text),
                        code_review_approved=(approved in code_review_text),
                        has_implementation_summary=(design_path / "implementation_summary.md").exists(),
                        has_implement_failed=_nonempty(design_path / "implement_failed.md"),
                        has_scope_check_pass=(design_path / "scope_check.pass").exists(),
                        has_scope_check_fail=(design_path / "scope_check.fail").exists(),
                        has_job_submitted=(design_path / "job_submitted.txt").exists(),
                        has_training_failed=(design_path / "training_failed.txt").exists(),
                        revision=row.get("Revision", ""),
                        stale_since=row.get("Stale_Since", ""),
                    )
                )

            ideas.append(
                IdeaState(
                    idea_id=idea_id,
                    idea_name=idea_name,
                    status=idea_status,
                    idea_md_path=idea_md,
                    expected_designs=expected,
                    designs=tuple(designs),
                )
            )

        return RichState(ctx=ctx, ideas=tuple(ideas))


def _nonempty(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


def _parse_expected_designs(idea_md: Path) -> int | None:
    text = store.read_text(idea_md)
    for line in text.splitlines():
        if line.lower().startswith("**expected designs:**"):
            tail = line.split(":", 1)[1].strip().strip("*").strip()
            try:
                return int(tail.split()[0])
            except (ValueError, IndexError):
                return None
    return None


def _infer_idea_name(idea_md: Path) -> str:
    text = store.read_text(idea_md)
    for line in text.splitlines():
        if line.lower().startswith("**idea name:**"):
            return line.split(":", 1)[1].strip().strip("*").strip()
    return ""
