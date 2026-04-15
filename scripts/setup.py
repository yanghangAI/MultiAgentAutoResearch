#!/usr/bin/env python3
"""Mechanical setup script for MultiAgentAutoResearch.

Takes the confirmed setup answers (from the Setup Agent's exploration) and
performs all deterministic work:
  1. Generate .automation.json
  2. Copy files into baseline/ and infra/
  3. Copy submission script templates
  4. Initialize tracking files (runs/idea_overview.csv, results.csv)

Usage (called by the Setup Agent after user confirms the 6-line summary):
    python scripts/setup.py \
        --project-dir /path/to/target \
        --primary-metric val_loss \
        --metric-fields train_loss,val_loss \
        --done-value 20 \
        --runtime local \
        --baseline-files train.py,model.py,config.py \
        --infra-files dataset.py,eval.py
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Set up the automation framework for a target project.",
    )
    p.add_argument(
        "--project-dir",
        type=Path,
        required=True,
        help="Path to the target project directory.",
    )
    p.add_argument(
        "--primary-metric",
        required=True,
        help="Name of the primary metric field (e.g. val_loss).",
    )
    p.add_argument(
        "--metric-fields",
        required=True,
        help="Comma-separated list of all metric field names.",
    )
    p.add_argument(
        "--done-value",
        type=int,
        default=20,
        help="Value of progress_field that marks a run as Done (default: 20).",
    )
    p.add_argument(
        "--runtime",
        choices=["local", "slurm"],
        default="local",
        help="Execution environment (default: local).",
    )
    p.add_argument(
        "--baseline-files",
        default="",
        help="Comma-separated list of filenames to copy into baseline/.",
    )
    p.add_argument(
        "--infra-files",
        default="",
        help="Comma-separated list of filenames to copy into infra/.",
    )
    # Optional overrides with sensible defaults
    p.add_argument(
        "--metrics-glob",
        default="**/metrics.csv",
        help="Glob pattern for metrics files (default: **/metrics.csv).",
    )
    p.add_argument(
        "--progress-field",
        default="epoch",
        help="Field name for progress tracking (default: epoch).",
    )
    p.add_argument(
        "--source-globs",
        default="*.py",
        help="Comma-separated glob patterns for setup-design file copy (default: *.py).",
    )
    p.add_argument(
        "--output-patch-target",
        default="config.py",
        help="Config file for output path patching (default: config.py).",
    )
    p.add_argument(
        "--output-patch-regex",
        default=r'(output_dir\s*=\s*)["\'].*?["\']',
        help="Regex for output path field in config file.",
    )
    p.add_argument(
        "--output-patch-replacement",
        default=r'\g<1>"{dst}"',
        help="Replacement template for output path patching.",
    )
    p.add_argument(
        "--max-jobs",
        type=int,
        default=30,
        help="Maximum concurrent jobs (default: 30).",
    )
    p.add_argument(
        "--dashboard-repo-url",
        default="",
        help="GitHub repo URL for dashboard (optional).",
    )
    return p.parse_args(argv)


def _split_csv(value: str) -> list[str]:
    """Split a comma-separated string, stripping whitespace and empty items."""
    return [s.strip() for s in value.split(",") if s.strip()]


def generate_automation_config(args: argparse.Namespace, repo_root: Path) -> dict:
    """Build and write .automation.json from parsed arguments."""
    metric_fields = _split_csv(args.metric_fields)
    source_globs = _split_csv(args.source_globs)

    if args.primary_metric not in metric_fields:
        print(
            f"Error: primary metric '{args.primary_metric}' "
            f"not found in metric_fields {metric_fields}",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.runtime == "slurm":
        job_count_cmd = 'squeue -u "$USER" -h | wc -l'
        train_template = "{root}/scripts/slurm/submit_train.sh {train_script} {job_name}"
        test_template = "sbatch -o {test_output}/slurm_test_%j.out {root}/scripts/slurm/slurm_test.sh {target_dir}"
    else:
        job_count_cmd = "pgrep -f train.py | wc -l"
        train_template = "bash {root}/scripts/local/submit_train.sh {train_script} {job_name}"
        test_template = "bash {root}/scripts/local/submit_test.sh {target_dir} {test_output}"

    config = {
        "results": {
            "metric_fields": metric_fields,
            "primary_metric": args.primary_metric,
            "metrics_glob": args.metrics_glob,
            "exclude_path_parts": ["test_output"],
        },
        "status": {
            "progress_field": args.progress_field,
            "done_value": args.done_value,
            "approved_token": "APPROVED",
        },
        "setup_design": {
            "source_globs": source_globs,
            "destination_subdir": "code",
            "output_patch": {
                "enabled": True,
                "target_file": args.output_patch_target,
                "regex": args.output_patch_regex,
                "replacement_template": args.output_patch_replacement,
            },
        },
        "submit": {
            "max_jobs_default": args.max_jobs,
            "job_count_command": job_count_cmd,
            "submit_train_command_template": train_template,
            "submit_test_command_template": test_template,
        },
        "dashboard": {
            "github_repo_url": args.dashboard_repo_url,
            "baseline_results": [],
        },
    }

    config_path = repo_root / ".automation.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {config_path}")
    return config


def copy_files(
    file_list: list[str],
    project_dir: Path,
    dest_dir: Path,
    label: str,
) -> list[str]:
    """Copy files from project_dir into dest_dir. Returns list of copied names."""
    if not file_list:
        return []

    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in file_list:
        src = project_dir / name
        if not src.exists():
            # Try finding it recursively
            matches = list(project_dir.rglob(name))
            if matches:
                src = matches[0]
            else:
                print(f"  warning: {name} not found in {project_dir}, skipping")
                continue
        dst = dest_dir / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(name)
        print(f"  {label}: {src} -> {dst}")
    return copied


def write_readme(dest_dir: Path, label: str, files: list[str]) -> None:
    """Write a simple README listing the files in the directory."""
    readme = dest_dir / "README.md"
    lines = [f"# {label}\n\n"]
    if files:
        lines.append("## Contents\n\n")
        for f in sorted(files):
            lines.append(f"- `{f}`\n")
    else:
        lines.append("No files copied yet.\n")
    readme.write_text("".join(lines), encoding="utf-8")
    print(f"  wrote {readme}")


def copy_submission_templates(runtime: str, repo_root: Path) -> None:
    """Copy example submission scripts to the active scripts directory."""
    examples_dir = repo_root / "scripts" / "examples" / runtime
    target_dir = repo_root / "scripts" / runtime

    if not examples_dir.exists():
        print(f"  warning: no example scripts at {examples_dir}")
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    for src in examples_dir.iterdir():
        if src.name == "__init__.py":
            continue
        dst = target_dir / src.name
        shutil.copy2(src, dst)
        # Preserve executable bit
        if src.suffix == ".sh":
            dst.chmod(dst.stat().st_mode | 0o111)
        print(f"  scripts: {src} -> {dst}")


def init_tracking_files(metric_fields: list[str], repo_root: Path) -> None:
    """Create runs/idea_overview.csv and results.csv if they don't exist."""
    runs = repo_root / "runs"
    runs.mkdir(parents=True, exist_ok=True)

    idea_csv = runs / "idea_overview.csv"
    if not idea_csv.exists():
        with idea_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Idea_ID", "Idea_Name", "Status", "created_at", "updated_at"])
        print(f"  wrote {idea_csv}")

    results_csv = repo_root / "results.csv"
    if not results_csv.exists():
        header = ["idea_id", "design_id", "status"] + metric_fields
        with results_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
        print(f"  wrote {results_csv}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        print(f"Error: project directory not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Setting up automation for: {project_dir}\n")

    # 1. Generate .automation.json
    print("[1/4] Generating .automation.json")
    generate_automation_config(args, repo_root)

    # 2. Copy files
    print("\n[2/4] Copying project files")
    baseline_files = _split_csv(args.baseline_files)
    infra_files = _split_csv(args.infra_files)

    baseline_dir = repo_root / "baseline"
    infra_dir = repo_root / "infra"

    copied_baseline = copy_files(baseline_files, project_dir, baseline_dir, "baseline")
    copied_infra = copy_files(infra_files, project_dir, infra_dir, "infra")

    write_readme(baseline_dir, "Baseline", copied_baseline)
    write_readme(infra_dir, "Infra", copied_infra)

    # Ensure infra/ is a package
    init_py = infra_dir / "__init__.py"
    if not init_py.exists():
        init_py.write_text("", encoding="utf-8")
        print(f"  wrote {init_py}")

    # 3. Copy submission script templates
    print(f"\n[3/4] Copying {args.runtime} submission script templates")
    copy_submission_templates(args.runtime, repo_root)

    # 4. Initialize tracking files
    print("\n[4/4] Initializing tracking files")
    metric_fields = _split_csv(args.metric_fields)
    init_tracking_files(metric_fields, repo_root)

    print("\nSetup complete. Next steps:")
    print("  - Sub-agent A: update agent prompts with project vocabulary")
    print("  - Sub-agent B: write infra/constants.py and customize submission scripts")


if __name__ == "__main__":
    main()
