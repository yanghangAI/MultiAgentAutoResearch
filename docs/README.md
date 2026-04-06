# Experiment Automation Template

This repository now contains a project-agnostic automation layer for:

- idea/design tracking
- agent workflow orchestration
- test/train job submission
- status synchronization
- dashboard generation/deployment

It is intentionally decoupled from any single model or dataset.

## Quick Start

1. Edit `.automation.yaml` for your project conventions.
2. Add your own project prompts under `agents/`.
3. Create ideas/designs under `runs/`.
4. Use `python scripts/cli.py ...` commands for workflow operations.

## Core Commands

```bash
python scripts/cli.py summarize-results
python scripts/cli.py sync-status
python scripts/cli.py setup-design <src> <dst>
python scripts/cli.py submit-test <design_dir>
python scripts/cli.py submit-train <train_script> <job_name>
python scripts/cli.py submit-implemented
python scripts/cli.py build-dashboard
python scripts/cli.py deploy-dashboard
```

## Project Adapters

The automation core is configured through `.automation.yaml` (JSON-compatible YAML):

- `results`: metric column names and metrics discovery rules
- `status`: completion epoch and approval marker token
- `setup_design`: source file patterns and optional output path patching
- `submit`: job-count command and submit command templates
- `dashboard`: optional GitHub URL and baseline tagging
