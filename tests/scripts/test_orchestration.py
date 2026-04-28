from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.context import ProjectContext
from scripts.lib.orchestration.scheduler import pick_next
from scripts.lib.orchestration.state import RichState
from scripts.lib.orchestration.transitions import next_action_for_idea


def _make_ctx(root: Path) -> ProjectContext:
    (root / ".automation.json").write_text("{}", encoding="utf-8")
    (root / "runs").mkdir(parents=True, exist_ok=True)
    (root / "runs" / "idea_overview.csv").write_text(
        "Idea_ID,Idea_Name,Status,created_at,updated_at\n",
        encoding="utf-8",
    )
    return ProjectContext.create(root)


def _make_idea(root: Path, idea_id: str, *, expected_designs: int = 1) -> Path:
    idea_dir = root / "runs" / idea_id
    idea_dir.mkdir(parents=True, exist_ok=True)
    (idea_dir / "idea.md").write_text(
        f"**Idea Name:** {idea_id}\n**Expected Designs:** {expected_designs}\n",
        encoding="utf-8",
    )
    (idea_dir / "design_overview.csv").write_text(
        "Design_ID,Design_Description,Status,Revision,Stale_Since,created_at,updated_at\n",
        encoding="utf-8",
    )
    return idea_dir


def _make_design(idea_dir: Path, design_id: str, *, design_md: bool = True) -> Path:
    d = idea_dir / design_id
    d.mkdir(parents=True, exist_ok=True)
    if design_md:
        (d / "design.md").write_text("**Design Description:** stub\n", encoding="utf-8")
    return d


def test_no_ideas_falls_through_to_architect(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    state = RichState.snapshot(ctx)
    assert pick_next(state).role == "Architect"


def test_idea_with_no_design_md_spawns_designer(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    _make_idea(tmp_path, "idea001")
    state = RichState.snapshot(ctx)
    action = pick_next(state)
    assert action.role == "Designer"
    assert action.idea_id == "idea001"


def test_design_md_without_review_spawns_design_reviewer(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    idea_dir = _make_idea(tmp_path, "idea001")
    _make_design(idea_dir, "design001")
    state = RichState.snapshot(ctx)
    action = pick_next(state)
    assert action.role == "Reviewer"
    assert action.review_mode == "design"


def test_approved_design_spawns_builder_per_design(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    idea_dir = _make_idea(tmp_path, "idea001")
    d = _make_design(idea_dir, "design001")
    (d / "design_review.md").write_text("APPROVED — go.", encoding="utf-8")
    state = RichState.snapshot(ctx)
    action = pick_next(state)
    assert action.role == "Builder"
    assert action.idea_id == "idea001"
    assert action.design_id == "design001"


def test_implemented_design_spawns_code_reviewer(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    idea_dir = _make_idea(tmp_path, "idea001")
    d = _make_design(idea_dir, "design001")
    (d / "design_review.md").write_text("APPROVED.", encoding="utf-8")
    (d / "implementation_summary.md").write_text("done", encoding="utf-8")
    state = RichState.snapshot(ctx)
    action = pick_next(state)
    assert action.role == "Reviewer"
    assert action.review_mode == "code"


def test_approved_code_review_triggers_submit(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    idea_dir = _make_idea(tmp_path, "idea001")
    d = _make_design(idea_dir, "design001")
    (d / "design_review.md").write_text("APPROVED.", encoding="utf-8")
    (d / "implementation_summary.md").write_text("done", encoding="utf-8")
    (d / "code_review.md").write_text("APPROVED — ship it.", encoding="utf-8")
    state = RichState.snapshot(ctx)
    action = pick_next(state)
    assert action.role == "Submit"


def test_implement_failed_skips_builder_and_advances(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    idea_dir = _make_idea(tmp_path, "idea001", expected_designs=1)
    d = _make_design(idea_dir, "design001")
    (d / "design_review.md").write_text("APPROVED.", encoding="utf-8")
    (d / "implement_failed.md").write_text("gave up: cannot implement", encoding="utf-8")
    state = RichState.snapshot(ctx)
    action = pick_next(state)
    # Only one design, all approved designs accounted for, no implementation
    # to review and no submission to make. Idle on this idea, fall through
    # to Architect.
    assert action.role == "Architect"


def test_fifo_ordering_picks_lowest_idea_id(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    _make_idea(tmp_path, "idea002")
    _make_idea(tmp_path, "idea001")
    state = RichState.snapshot(ctx)
    action = pick_next(state)
    assert action.idea_id == "idea001"


def test_prefer_in_flight_promotes_idea_with_designs(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    _make_idea(tmp_path, "idea001")  # fresh, no designs
    idea_dir2 = _make_idea(tmp_path, "idea002")
    _make_design(idea_dir2, "design001")  # in-flight
    state = RichState.snapshot(ctx)
    action = pick_next(state, prefer_in_flight=True)
    assert action.idea_id == "idea002"


def test_designer_runs_again_when_below_expected_designs(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    idea_dir = _make_idea(tmp_path, "idea001", expected_designs=2)
    d = _make_design(idea_dir, "design001")
    # design has been reviewed (so Designer is not racing Reviewer)
    (d / "design_review.md").write_text("APPROVED.", encoding="utf-8")
    # also implemented + code-reviewed + submitted, so it's done from the
    # orchestrator's per-design perspective
    (d / "implementation_summary.md").write_text("done", encoding="utf-8")
    (d / "code_review.md").write_text("APPROVED.", encoding="utf-8")
    (d / "job_submitted.txt").write_text("submitted", encoding="utf-8")
    state = RichState.snapshot(ctx)
    action = next_action_for_idea(state.ideas[0])
    assert action is not None and action.role == "Designer"
