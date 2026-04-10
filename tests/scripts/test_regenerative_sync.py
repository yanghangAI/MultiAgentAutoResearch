from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.context import ProjectContext
from scripts.lib.status import sync_all


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def setup_idea_with_designs(tmp_path: Path) -> None:
    """Create filesystem state for idea001 with 2 designs."""
    idea_dir = tmp_path / "runs" / "idea001"
    idea_dir.mkdir(parents=True)
    (idea_dir / "idea.md").write_text(
        "**Idea Name:** Test Idea\n**Expected Designs:** 2\n**Approach:** test\n**Baseline Source:** baseline/\n",
        encoding="utf-8",
    )
    d1 = idea_dir / "design001"
    d1.mkdir()
    (d1 / "design.md").write_text("**Design Description:** First Design\n", encoding="utf-8")
    (d1 / "design_review.md").write_text("APPROVED\n", encoding="utf-8")
    (d1 / "code_review.md").write_text("APPROVED\n", encoding="utf-8")

    d2 = idea_dir / "design002"
    d2.mkdir()
    (d2 / "design.md").write_text("**Design Description:** Second Design\n", encoding="utf-8")
    (d2 / "design_review.md").write_text("APPROVED\n", encoding="utf-8")


def test_sync_all_builds_csvs_from_scratch(tmp_path: Path) -> None:
    """sync_all should produce correct CSVs even with no pre-existing CSVs."""
    setup_idea_with_designs(tmp_path)

    # No CSVs exist yet
    assert not (tmp_path / "runs" / "idea_overview.csv").exists()

    sync_all(ProjectContext.create(tmp_path))

    idea_csv = (tmp_path / "runs" / "idea_overview.csv").read_text(encoding="utf-8")
    design_csv = (tmp_path / "runs" / "idea001" / "design_overview.csv").read_text(encoding="utf-8")
    assert "idea001" in idea_csv
    assert "Test Idea" in idea_csv
    assert "design001" in design_csv
    assert "design002" in design_csv
    assert "Implemented" in design_csv  # design001 has code_review approved
    assert "Not Implemented" in design_csv  # design002 only has design_review


def test_sync_all_is_idempotent(tmp_path: Path) -> None:
    """Running sync_all twice produces identical CSV content."""
    setup_idea_with_designs(tmp_path)

    sync_all(ProjectContext.create(tmp_path))
    idea_csv_1 = (tmp_path / "runs" / "idea_overview.csv").read_text(encoding="utf-8")
    design_csv_1 = (tmp_path / "runs" / "idea001" / "design_overview.csv").read_text(encoding="utf-8")

    sync_all(ProjectContext.create(tmp_path))
    idea_csv_2 = (tmp_path / "runs" / "idea_overview.csv").read_text(encoding="utf-8")
    design_csv_2 = (tmp_path / "runs" / "idea001" / "design_overview.csv").read_text(encoding="utf-8")

    # Strip timestamps for comparison (they may differ by seconds)
    def strip_timestamps(text: str) -> str:
        import re
        return re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "TIME", text)

    assert strip_timestamps(idea_csv_1) == strip_timestamps(idea_csv_2)
    assert strip_timestamps(design_csv_1) == strip_timestamps(design_csv_2)


def test_sync_all_discards_stale_csv_rows(tmp_path: Path) -> None:
    """Manually-added CSV rows with no filesystem backing are not preserved."""
    setup_idea_with_designs(tmp_path)

    # Pre-populate CSV with a ghost row that has no filesystem backing
    write_csv(
        tmp_path / "runs" / "idea_overview.csv",
        ["Idea_ID", "Idea_Name", "Status", "created_at", "updated_at"],
        [
            ["idea001", "Test Idea", "Not Designed", "", ""],
            ["idea999", "Ghost Idea", "Done", "", ""],  # no filesystem backing
        ],
    )

    sync_all(ProjectContext.create(tmp_path))

    idea_csv = (tmp_path / "runs" / "idea_overview.csv").read_text(encoding="utf-8")
    assert "idea001" in idea_csv
    assert "idea999" not in idea_csv
