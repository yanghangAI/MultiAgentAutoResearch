from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.lib import layout, store
from scripts.lib.models import Status


def implemented_design_dirs(root: Path | None = None) -> list[Path]:
    root_path = layout.repo_root(root)
    found: list[Path] = []
    for csv_path in sorted(layout.runs_dir(root_path).glob("**/design_overview.csv")):
        rows = store.read_csv_rows(csv_path)
        idea_id = csv_path.parent.name
        for row in rows[1:]:
            if row and len(row) >= 3 and row[2].strip() == Status.IMPLEMENTED:
                found.append(layout.design_dir(idea_id, row[0].strip(), root_path))
    return found


def current_job_count() -> int:
    result = subprocess.run(
        ["bash", "-lc", 'squeue -u "$USER" -h | wc -l'],
        text=True,
        capture_output=True,
        check=True,
    )
    return int(result.stdout.strip() or "0")


def submit_train_script(train_script: Path, job_name: str, root: Path) -> None:
    subprocess.run(
        [str(root / "scripts" / "slurm" / "submit_train.sh"), str(train_script), job_name],
        check=True,
    )


def submit_test(root: Path | None = None, target_dir: Path | None = None, dry_run: bool = False) -> Path:
    root_path = layout.repo_root(root)
    target = Path(target_dir or Path.cwd()).resolve()
    test_output = target / "test_output"
    test_output.mkdir(parents=True, exist_ok=True)

    command = [
        "sbatch",
        "-o",
        str(test_output / "slurm_test_%j.out"),
        str(root_path / "scripts" / "slurm" / "slurm_test.sh"),
        str(target),
    ]
    if dry_run:
        print("DRY RUN: would submit test job:")
        print(" ".join(command))
        return test_output

    subprocess.run(command, check=True)
    print(f"Submitted test job for {target}")
    return test_output


def submit_implemented(
    root: Path | None = None,
    max_jobs: int = 30,
    dry_run: bool = False,
) -> list[str]:
    root_path = layout.repo_root(root)
    submitted: list[str] = []
    for design_path in implemented_design_dirs(root_path):
        current_jobs = 0 if dry_run else current_job_count()
        if current_jobs >= max_jobs:
            print(f"Job limit reached ({current_jobs}/{max_jobs}). Pausing submissions.")
            break
        train_script = layout.resolve_train_script(design_path)
        if not train_script.is_file():
            print(f"Warning: {train_script} does not exist! Skipping.")
            continue
        job_name = f"{design_path.parent.name}-{design_path.name}"
        if dry_run:
            print(f"DRY RUN: would submit training job for {job_name} using {train_script}")
        else:
            print(
                f"Submitting training job for {job_name} "
                f"({current_jobs}/{max_jobs} jobs running)..."
            )
            submit_train_script(train_script, job_name, root_path)
        submitted.append(job_name)
    if not submitted:
        print("No 'Implemented' designs found waiting for submission.")
    return submitted
