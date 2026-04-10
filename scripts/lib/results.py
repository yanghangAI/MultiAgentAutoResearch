from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from scripts.lib import layout, store
from scripts.lib.models import ResultRecord

if TYPE_CHECKING:
    from scripts.lib.context import ProjectContext


def _core_result_fields(progress_field: str) -> list[str]:
    return ["idea_id", "design_id", progress_field]


def discover_metrics_files(ctx: ProjectContext) -> list[Path]:
    metrics = layout.runs_dir(ctx.root).glob(ctx.cfg.results.metrics_glob)
    excluded = set(ctx.cfg.results.exclude_path_parts)
    return sorted(path for path in metrics if excluded.isdisjoint(path.parts))


def parse_metrics_file(metrics_path: Path, ctx: ProjectContext) -> ResultRecord | None:
    progress_field = ctx.cfg.status.progress_field
    rows = store.read_dict_rows(metrics_path)
    if not rows:
        return None
    last_row = rows[-1]
    metric_values = [last_row.get(field) for field in ctx.cfg.results.metric_fields]
    if all(value is None for value in metric_values):
        return None
    idea_id, design_id = layout.parse_idea_design_from_metrics(metrics_path)
    metrics = {field: last_row.get(field, "") for field in ctx.cfg.results.metric_fields}
    return ResultRecord(
        idea_id=idea_id,
        design_id=design_id,
        progress=last_row.get(progress_field, ""),
        metrics=metrics,
    )


def summarize_results(ctx: ProjectContext) -> list[ResultRecord]:
    progress_field = ctx.cfg.status.progress_field
    records: list[ResultRecord] = []
    for metrics_path in discover_metrics_files(ctx):
        try:
            record = parse_metrics_file(metrics_path, ctx)
        except Exception as exc:
            print(f"Error reading {metrics_path}: {exc}")
            continue
        if record is not None:
            records.append(record)

    records.sort(key=lambda item: (item.idea_id, item.design_id))
    result_fields = _core_result_fields(progress_field) + list(ctx.cfg.results.metric_fields)
    out_rows = [
        {
            "idea_id": record.idea_id,
            "design_id": record.design_id,
            progress_field: record.progress,
            **record.metrics,
        }
        for record in records
    ]
    if out_rows:
        store.write_dict_rows(layout.results_csv_path(ctx.root), result_fields, out_rows)
        print(
            f"Successfully summarized {len(out_rows)} results into "
            f"{layout.results_csv_path(ctx.root)}"
        )
    else:
        print("No valid training metrics.csv files found with the required metric columns.")
    return records
