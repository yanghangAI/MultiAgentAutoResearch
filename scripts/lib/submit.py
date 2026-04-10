from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.lib import layout, store
from scripts.lib.models import Status

if TYPE_CHECKING:
    from scripts.lib.context import ProjectContext


def implemented_design_dirs(ctx: ProjectContext) -> list[Path]:
    root_path = ctx.root
    found: list[Path] = []
    for csv_path in sorted(layout.runs_dir(root_path).glob("**/design_overview.csv")):
        rows = store.read_csv_rows(csv_path)
        idea_id = csv_path.parent.name
        for row in rows[1:]:
            if row and len(row) >= 3 and row[2].strip() == Status.IMPLEMENTED:
                found.append(layout.design_dir(idea_id, row[0].strip(), root_path))
    return found


def _format_shell_template(template: str, **kwargs: str) -> str:
    return template.format(**{key: shlex.quote(value) for key, value in kwargs.items()})


def current_job_count(ctx: ProjectContext) -> int:
    cfg = ctx.cfg
    if not cfg.submit.job_count_command:
        return 0
    result = subprocess.run(
        ["bash", "-lc", cfg.submit.job_count_command],
        text=True,
        capture_output=True,
        check=True,
    )
    return int(result.stdout.strip() or "0")


def submit_train_script(train_script: Path, job_name: str, ctx: ProjectContext) -> None:
    cfg = ctx.cfg
    if not cfg.submit.submit_train_command_template:
        raise SystemExit("submit_train_command_template is not configured in .automation.json.")
    command = _format_shell_template(
        cfg.submit.submit_train_command_template,
        root=str(ctx.root),
        train_script=str(train_script),
        job_name=job_name,
    )
    subprocess.run(
        ["bash", "-lc", command],
        check=True,
    )


def submit_test(ctx: ProjectContext, target_dir: Path | None = None, dry_run: bool = False) -> Path:
    cfg = ctx.cfg
    root_path = ctx.root
    target = Path(target_dir or Path.cwd()).resolve()
    test_output = target / "test_output"
    test_output.mkdir(parents=True, exist_ok=True)

    if not cfg.submit.submit_test_command_template:
        raise SystemExit("submit_test_command_template is not configured in .automation.json.")
    command = _format_shell_template(
        cfg.submit.submit_test_command_template,
        root=str(root_path),
        target_dir=str(target),
        test_output=str(test_output),
    )
    if dry_run:
        print("DRY RUN: would submit test job:")
        print(command)
        return test_output

    subprocess.run(["bash", "-lc", command], check=True)
    print(f"Submitted test job for {target}")
    return test_output


def submit_implemented(
    ctx: ProjectContext,
    max_jobs: int | None = None,
    dry_run: bool = False,
) -> list[str]:
    cfg = ctx.cfg
    root_path = ctx.root
    max_jobs = max_jobs if max_jobs is not None else cfg.submit.max_jobs_default
    submitted: list[str] = []
    for design_path in implemented_design_dirs(ctx):
        current_jobs = 0 if dry_run else current_job_count(ctx)
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
            (design_path / "job_submitted.txt").write_text(
                f"Submitted: {job_name}\n", encoding="utf-8"
            )
            submit_train_script(train_script, job_name, ctx)
        submitted.append(job_name)
    if not submitted:
        print("No 'Implemented' designs found waiting for submission.")
    return submitted
