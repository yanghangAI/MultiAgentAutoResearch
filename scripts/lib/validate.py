from __future__ import annotations

import csv
from pathlib import Path

from scripts.lib import layout
from scripts.lib.project_config import load_project_config


def validate_config(root: Path | None = None, search_dir: Path | None = None) -> None:
    root_path = layout.repo_root(root)
    cfg = load_project_config(root_path)
    errors: list[str] = []
    warnings: list[str] = []

    # --- Static checks ---
    if not cfg.results.metric_fields:
        errors.append("results.metric_fields is empty — no metrics to track.")
    if cfg.results.primary_metric not in cfg.results.metric_fields:
        errors.append(
            f"primary_metric '{cfg.results.primary_metric}' is not in "
            f"metric_fields {list(cfg.results.metric_fields)}."
        )
    if cfg.status.done_epoch <= 0:
        errors.append(f"status.done_epoch must be > 0, got {cfg.status.done_epoch}.")
    if not cfg.submit.submit_train_command_template:
        warnings.append("submit.submit_train_command_template is not configured.")
    if not cfg.submit.submit_test_command_template:
        warnings.append("submit.submit_test_command_template is not configured.")

    # --- Dynamic checks ---
    if search_dir is not None:
        search_path = search_dir if search_dir.is_absolute() else (root_path / search_dir)
        search_path = search_path.resolve()
        if not search_path.exists():
            errors.append(f"--search-dir '{search_path}' does not exist.")
        else:
            # Do not apply exclude_path_parts when the user explicitly provides a
            # search dir — they may intentionally point at test_output/ or similar.
            metrics_files = list(search_path.glob(cfg.results.metrics_glob))
            if not metrics_files:
                errors.append(
                    f"metrics_glob '{cfg.results.metrics_glob}' found no files under "
                    f"'{search_path}'. Check that your training code writes metrics to "
                    f"the expected path and filename."
                )
            else:
                print(f"Found {len(metrics_files)} metrics file(s) matching glob.")
                for metrics_path in metrics_files[:5]:
                    with metrics_path.open(newline="", encoding="utf-8") as fh:
                        reader = csv.DictReader(fh)
                        headers = list(reader.fieldnames or [])
                    missing_cols = [f for f in cfg.results.metric_fields if f not in headers]
                    if missing_cols:
                        errors.append(
                            f"{metrics_path.relative_to(root_path)}: missing columns "
                            f"{missing_cols}. Found columns: {headers}."
                        )
                    else:
                        print(
                            f"  {metrics_path.relative_to(root_path)}: "
                            f"all metric columns present. ✓"
                        )

    # --- Report ---
    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")

    if errors:
        raise SystemExit(
            f"\nConfig validation failed with {len(errors)} error(s). "
            "Fix .automation.yaml before starting the research loop."
        )
    print("Config validation passed.")
