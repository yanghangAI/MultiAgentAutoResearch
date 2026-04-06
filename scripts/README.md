# Scripts

This directory contains the automation layer for tracking experiments, summarizing results, submitting jobs, and building or deploying the project dashboard.

## Architecture

The script system now has two layers:

1. `scripts/cli.py`
   The main entrypoint for script workflows.
2. `scripts/lib/`
   Shared Python modules that hold the actual logic.
3. `scripts/tools/`
   Standalone utilities such as design setup and diff helpers.
4. `scripts/slurm/`
   Low-level SLURM submission and job scripts.

Most legacy shell and Python entrypoints have been moved to `scripts/old/`. They remain as compatibility wrappers around the CLI for older workflows.

## Main Commands

Run these from the repo root:

```bash
python scripts/cli.py summarize-results
python scripts/cli.py sync-status
python scripts/cli.py setup-design baseline/ runs/idea001/design001
python scripts/cli.py submit-test runs/idea001/design001
python scripts/cli.py submit-train runs/idea001/design001/code/train.py idea001-design001
python scripts/cli.py submit-implemented
python scripts/cli.py build-dashboard
python scripts/cli.py deploy-dashboard
python scripts/cli.py update-all
```

What each command does:

- `summarize-results`
  Scans `runs/` for training `metrics.csv` files, ignores `test_output/`, and writes a consolidated `results.csv`.
- `sync-status`
  Regenerates `results.csv` and then updates idea and design statuses in the overview CSVs based on metrics, review files, and SLURM outputs.
- `setup-design <src> <dst>`
  Copies Python files from a baseline or prior design into `<dst>/code/` and patches `config.py` so outputs land in the destination design folder.
- `submit-test <design_dir>`
  Submits a short 2-epoch sanity-check SLURM job for a design and writes logs/results into `<design_dir>/test_output/`.
- `submit-train <train.py> [job_name]`
  Submits a full training SLURM job for a specific training script.
- `submit-implemented`
  Finds designs currently marked `Implemented` and submits full training jobs for them, respecting the configured job cap.
- `build-dashboard`
  Reads the tracking CSVs and generates `website/index.html`.
- `deploy-dashboard`
  Copies the generated dashboard to the `gh-pages` branch and optionally pushes it, while refusing dirty-tree deploys unless explicitly allowed.
- `update-all`
  Runs the full dashboard-refresh workflow: sync statuses, rebuild the dashboard, and deploy it.

Useful options:

```bash
python scripts/cli.py submit-test runs/idea001/design001 --dry-run
python scripts/cli.py submit-implemented --dry-run
python scripts/cli.py submit-implemented --max-jobs 10
python scripts/cli.py deploy-dashboard --allow-dirty
python scripts/cli.py deploy-dashboard --no-push
python scripts/cli.py update-all --allow-dirty
```

## Module Guide

- `lib/models.py`
  Shared status constants and lightweight record types.
- `lib/layout.py`
  Repo path helpers and canonical design/code layout resolution.
- `lib/store.py`
  CSV and text file helpers.
- `lib/results.py`
  Metrics discovery and `results.csv` generation.
- `lib/status.py`
  Idea/design status updates and sync logic.
- `lib/submit.py`
  Test submission plus implemented-design discovery and SLURM submission flow.
- `lib/dashboard.py`
  Dashboard data preparation and HTML rendering.
- `lib/deploy.py`
  Git-based dashboard deployment to `gh-pages`.
- `tools/setup_design.py`
  Copies a baseline or prior design into a new design folder and patches `output_dir`.
- `tools/show_diff.sh`
  Diff helper for newer `code/`-based designs.
- `tools/show_code_diff.sh`
  Diff helper with explicit or inferred starting points.
- `slurm/submit_train.sh`
  Low-level training-job submission wrapper.
- `slurm/submit_test.sh`
  Low-level sanity-test submission wrapper.
- `slurm/slurm_train.sh`
  Full training SLURM job script.
- `slurm/slurm_test.sh`
  Short sanity-check SLURM job script.

## Legacy Wrappers

The old non-SLURM entrypoints now live in `scripts/old/` and delegate to the new CLI:

- `old/run_summarize.sh`
- `old/update_all.sh`
- `old/auto_sync_status.sh`
- `old/auto_submit.sh`
- `old/deploy_website.sh`
- `old/generate_website.py`
- `old/summarize_results.py`
- `old/tracker.py`

## Folder Layout

Current top-level layout:

```text
scripts/
  cli.py
  lib/
  slurm/
  tools/
  old/
```

## Expected Layout

The canonical design layout is:

```text
runs/<idea_id>/<design_id>/
  code/
    train.py
    config.py
```

Submission logic prefers `code/train.py`, but still falls back to a flat `train.py` if needed for older designs.

## Safety Notes

- `deploy-dashboard` only stages the generated dashboard output.
- `deploy-dashboard` refuses to run on a dirty git tree unless `--allow-dirty` is passed.
- `sync-status` regenerates `results.csv` before recalculating idea and design statuses.
- `submit-test --dry-run` previews the sanity-check SLURM submission without calling `sbatch`.
- `submit-implemented --dry-run` is the safest way to inspect pending submissions.

## Testing

The script-layer regression tests live in:

```text
tests/scripts/test_architecture.py
```

Run them with:

```bash
pytest -q tests/scripts/test_architecture.py
```
