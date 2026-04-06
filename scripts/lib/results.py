from __future__ import annotations

from pathlib import Path

from scripts.lib import layout, store
from scripts.lib.models import ResultRecord


RESULT_FIELDS = [
    "idea_id",
    "design_id",
    "epoch",
    "train_mpjpe_weighted",
    "val_mpjpe_weighted",
]


def discover_metrics_files(root: Path | None = None) -> list[Path]:
    metrics = layout.runs_dir(root).glob("**/metrics.csv")
    return sorted(path for path in metrics if "test_output" not in path.parts)


def parse_metrics_file(metrics_path: Path) -> ResultRecord | None:
    rows = store.read_dict_rows(metrics_path)
    if not rows:
        return None
    last_row = rows[-1]
    train_mpjpe = last_row.get("train_mpjpe_weighted")
    val_mpjpe = last_row.get("val_mpjpe_weighted")
    if train_mpjpe is None and val_mpjpe is None:
        return None
    idea_id, design_id = layout.parse_idea_design_from_metrics(metrics_path)
    return ResultRecord(
        idea_id=idea_id,
        design_id=design_id,
        epoch=last_row.get("epoch", ""),
        train_mpjpe_weighted=train_mpjpe or "",
        val_mpjpe_weighted=val_mpjpe or "",
    )


def summarize_results(root: Path | None = None) -> list[ResultRecord]:
    records: list[ResultRecord] = []
    for metrics_path in discover_metrics_files(root):
        try:
            record = parse_metrics_file(metrics_path)
        except Exception as exc:
            print(f"Error reading {metrics_path}: {exc}")
            continue
        if record is not None:
            records.append(record)

    records.sort(key=lambda item: (item.idea_id, item.design_id))
    out_rows = [
        {
            "idea_id": record.idea_id,
            "design_id": record.design_id,
            "epoch": record.epoch,
            "train_mpjpe_weighted": record.train_mpjpe_weighted,
            "val_mpjpe_weighted": record.val_mpjpe_weighted,
        }
        for record in records
    ]
    if out_rows:
        store.write_dict_rows(layout.results_csv_path(root), RESULT_FIELDS, out_rows)
        print(
            f"Successfully summarized {len(out_rows)} results into "
            f"{layout.results_csv_path(root)}"
        )
    else:
        print("No valid training metrics.csv files found with the required metric columns.")
    return records
