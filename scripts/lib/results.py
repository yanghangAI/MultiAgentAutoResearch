from __future__ import annotations

from pathlib import Path

from scripts.lib import layout, store
from scripts.lib.project_config import load_project_config
from scripts.lib.models import ResultRecord


CORE_RESULT_FIELDS = ["idea_id", "design_id", "epoch"]


def discover_metrics_files(root: Path | None = None) -> list[Path]:
    cfg = load_project_config(root)
    metrics = layout.runs_dir(root).glob(cfg.results.metrics_glob)
    excluded = set(cfg.results.exclude_path_parts)
    return sorted(path for path in metrics if excluded.isdisjoint(path.parts))


def parse_metrics_file(metrics_path: Path, root: Path | None = None) -> ResultRecord | None:
    cfg = load_project_config(root)
    rows = store.read_dict_rows(metrics_path)
    if not rows:
        return None
    last_row = rows[-1]
    metric_values = [last_row.get(field) for field in cfg.results.metric_fields]
    if all(value is None for value in metric_values):
        return None
    idea_id, design_id = layout.parse_idea_design_from_metrics(metrics_path)
    train_metric = last_row.get(cfg.results.metric_fields[0], "") if cfg.results.metric_fields else ""
    val_metric = (
        last_row.get(cfg.results.metric_fields[1], "")
        if len(cfg.results.metric_fields) > 1
        else ""
    )
    return ResultRecord(
        idea_id=idea_id,
        design_id=design_id,
        epoch=last_row.get("epoch", ""),
        train_mpjpe_weighted=train_metric or "",
        val_mpjpe_weighted=val_metric or "",
    )


def summarize_results(root: Path | None = None) -> list[ResultRecord]:
    cfg = load_project_config(root)
    records: list[ResultRecord] = []
    for metrics_path in discover_metrics_files(root):
        try:
            record = parse_metrics_file(metrics_path, root=root)
        except Exception as exc:
            print(f"Error reading {metrics_path}: {exc}")
            continue
        if record is not None:
            records.append(record)

    records.sort(key=lambda item: (item.idea_id, item.design_id))
    result_fields = CORE_RESULT_FIELDS + list(cfg.results.metric_fields)
    out_rows = [
        {
            "idea_id": record.idea_id,
            "design_id": record.design_id,
            "epoch": record.epoch,
            **(
                {cfg.results.metric_fields[0]: record.train_mpjpe_weighted}
                if cfg.results.metric_fields
                else {}
            ),
            **(
                {cfg.results.metric_fields[1]: record.val_mpjpe_weighted}
                if len(cfg.results.metric_fields) > 1
                else {}
            ),
        }
        for record in records
    ]
    if out_rows:
        store.write_dict_rows(layout.results_csv_path(root), result_fields, out_rows)
        print(
            f"Successfully summarized {len(out_rows)} results into "
            f"{layout.results_csv_path(root)}"
        )
    else:
        print("No valid training metrics.csv files found with the required metric columns.")
    return records
