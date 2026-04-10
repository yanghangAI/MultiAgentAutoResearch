from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.context import ProjectContext
from scripts.lib.dashboard import build_dashboard


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def test_dashboard_renders_na_for_non_numeric_metrics(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "runs" / "idea_overview.csv",
        ["Idea_ID", "Idea_Name", "Status"],
        [["idea001", "Idea One", "Training"]],
    )
    write_csv(
        tmp_path / "results.csv",
        ["idea_id", "design_id", "epoch", "train_mpjpe_weighted", "val_mpjpe_weighted"],
        [
            ["idea001", "design001", "10", "corrupted", "9.0"],
            ["idea001", "design002", "5", "", "nan"],
        ],
    )
    (tmp_path / "runs" / "idea001").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs" / "idea001" / "idea.md").write_text("idea body\n", encoding="utf-8")

    build_dashboard(ProjectContext.create(tmp_path))

    html = (tmp_path / "website" / "index.html").read_text(encoding="utf-8")
    assert "N/A" in html
    assert "9.00" in html
