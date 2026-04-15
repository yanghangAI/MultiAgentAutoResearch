from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.context import ProjectContext
from scripts.lib.layout import parse_idea_design_from_metrics
from scripts.lib.submit import submit_implemented


def test_parse_idea_design_from_standard_path() -> None:
    path = Path("runs/idea001/design002/metrics.csv")
    assert parse_idea_design_from_metrics(path) == ("idea001", "design002")


def test_parse_idea_design_returns_unknown_for_unrecognized_path() -> None:
    path = Path("some/other/baseline/metrics.csv")
    assert parse_idea_design_from_metrics(path) == ("unknown", "unknown")


def test_parse_idea_design_baseline() -> None:
    path = Path("runs/baseline/metrics.csv")
    assert parse_idea_design_from_metrics(path) == ("baseline", "baseline")


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def test_job_submitted_written_before_submit_command(tmp_path: Path) -> None:
    """Verify job_submitted.txt exists before the submission command runs."""
    write_csv(
        tmp_path / "runs" / "idea001" / "design_overview.csv",
        ["Design_ID", "Design_Description", "Status"],
        [["design001", "first", "Implemented"]],
    )
    design = tmp_path / "runs" / "idea001" / "design001" / "code"
    design.mkdir(parents=True)
    (design / "train.py").write_text("print('train')\n", encoding="utf-8")

    # Configure a submit command that checks job_submitted.txt already exists
    (tmp_path / ".automation.json").write_text(
        '{"results": {"metric_fields": ["val_loss"], "primary_metric": "val_loss"}, '
        '"submit": {"submit_train_command_template": '
        '"test -f {root}/runs/idea001/design001/job_submitted.txt"}}',
        encoding="utf-8",
    )

    submitted = submit_implemented(ProjectContext.create(tmp_path))
    assert "idea001-design001" in submitted
    assert (tmp_path / "runs" / "idea001" / "design001" / "job_submitted.txt").exists()
