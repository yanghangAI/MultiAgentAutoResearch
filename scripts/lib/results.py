from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from scripts.lib import layout, scope as scope_mod, store
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


def _resolve_parent_key(design_path: Path, root: Path) -> tuple[str, str] | None:
    """Map a design's `.parent` file to a (idea_id, design_id) record key.

    Returns None if the design has no parent or its parent is not a tracked
    record (e.g., points to a path outside `runs/`).
    """
    parent_path = scope_mod.read_parent(design_path)
    if parent_path is None:
        return None
    if parent_path.name == "code":
        parent_path = parent_path.parent
    ref = layout.parse_design_ref(parent_path)
    if ref is not None:
        return ref
    try:
        if parent_path.resolve() == (root / "baseline").resolve():
            return ("baseline", "baseline")
    except OSError:
        pass
    return None


def summarize_results(ctx: ProjectContext) -> list[ResultRecord]:
    progress_field = ctx.cfg.status.progress_field
    primary = ctx.cfg.results.primary_metric
    records: list[ResultRecord] = []
    skipped_tainted = 0
    for metrics_path in discover_metrics_files(ctx):
        try:
            record = parse_metrics_file(metrics_path, ctx)
        except Exception as exc:
            print(f"Error reading {metrics_path}: {exc}")
            continue
        if record is None:
            continue
        if record.idea_id.startswith("idea") and record.design_id.startswith("design"):
            design_path = layout.design_dir(record.idea_id, record.design_id, ctx.root)
            if scope_mod.is_tainted(design_path, root=ctx.root):
                skipped_tainted += 1
                continue
        records.append(record)
    if skipped_tainted:
        print(f"Skipped {skipped_tainted} tainted design(s) from results aggregation.")

    records.sort(key=lambda item: (item.idea_id, item.design_id))

    primary_by_key: dict[tuple[str, str], float] = {}
    for record in records:
        try:
            primary_by_key[(record.idea_id, record.design_id)] = float(
                record.metrics.get(primary, "")
            )
        except (TypeError, ValueError):
            continue

    result_fields = (
        _core_result_fields(progress_field)
        + list(ctx.cfg.results.metric_fields)
        + ["delta_vs_parent"]
    )

    def _delta(record: ResultRecord) -> str:
        self_key = (record.idea_id, record.design_id)
        if self_key not in primary_by_key:
            return ""
        design_path = layout.design_dir(record.idea_id, record.design_id, ctx.root)
        parent_key = _resolve_parent_key(design_path, ctx.root)
        if parent_key is None or parent_key == self_key:
            return ""
        if parent_key not in primary_by_key:
            return ""
        return f"{primary_by_key[self_key] - primary_by_key[parent_key]:.6g}"

    out_rows = [
        {
            "idea_id": record.idea_id,
            "design_id": record.design_id,
            progress_field: record.progress,
            **record.metrics,
            "delta_vs_parent": _delta(record),
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
