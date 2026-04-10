from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.project_config import ProjectConfig, StatusConfig, ResultsConfig
from scripts.lib.status import derive_design_status


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def setup_design_with_metrics(tmp_path: Path, progress_field: str, progress_value: str, metric_fields: tuple[str, ...] = ("val_loss",)) -> None:
    design = tmp_path / "runs" / "idea001" / "design001"
    design.mkdir(parents=True, exist_ok=True)
    (design / "design.md").write_text("**Design Description:** test\n", encoding="utf-8")
    (design / "design_review.md").write_text("APPROVED\n", encoding="utf-8")
    (design / "code_review.md").write_text("APPROVED\n", encoding="utf-8")
    (design / "job_submitted.txt").write_text("Submitted: test\n", encoding="utf-8")
    write_csv(
        tmp_path / "results.csv",
        ["idea_id", "design_id", progress_field, *metric_fields],
        [["idea001", "design001", progress_value, *["0.5"] * len(metric_fields)]],
    )


def test_custom_progress_field_marks_done(tmp_path: Path) -> None:
    """Using 'step' as progress_field with done_value=50000 marks design as Done."""
    setup_design_with_metrics(tmp_path, "step", "50000")
    cfg = ProjectConfig(
        results=ResultsConfig(metric_fields=("val_loss",), primary_metric="val_loss"),
        status=StatusConfig(progress_field="step", done_value=50000),
    )
    status = derive_design_status("idea001", "design001", root=tmp_path, cfg=cfg)
    assert status == "Done"


def test_custom_progress_field_marks_training_when_below_threshold(tmp_path: Path) -> None:
    """Using 'step' with value below done_value marks design as Training."""
    setup_design_with_metrics(tmp_path, "step", "10000")
    cfg = ProjectConfig(
        results=ResultsConfig(metric_fields=("val_loss",), primary_metric="val_loss"),
        status=StatusConfig(progress_field="step", done_value=50000),
    )
    status = derive_design_status("idea001", "design001", root=tmp_path, cfg=cfg)
    assert status == "Training"


def test_default_progress_field_is_epoch(tmp_path: Path) -> None:
    """Default config still uses 'epoch' as progress field."""
    setup_design_with_metrics(tmp_path, "epoch", "20")
    cfg = ProjectConfig(
        results=ResultsConfig(metric_fields=("val_loss",), primary_metric="val_loss"),
        status=StatusConfig(done_value=20),
    )
    status = derive_design_status("idea001", "design001", root=tmp_path, cfg=cfg)
    assert status == "Done"
