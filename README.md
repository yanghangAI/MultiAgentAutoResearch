# Multi-Agent Auto Research

Multi-Agent Auto Research is a reusable multi-agent automation framework for research and ML projects. It gives you a consistent operating model for running iterative experiments end to end: define ideas, draft design variants, implement and review changes, submit runs, track status, summarize results, and publish a dashboard.

The system is designed to be **project-agnostic**: you adapt behavior with configuration and agent prompts, rather than rewriting the automation core.

## What This Project Does

At a high level, this repository provides:

- A multi-agent workflow scaffold (Architect, Designer, Builder, Reviewer, Orchestrator)
- A standardized experiment tracker (`idea` -> `design` lifecycle)
- CLI utilities for result aggregation, status synchronization, run submission, and dashboard generation
- A configurable setup layer (`.automation.yaml`) so the same framework can support different domains
- Clear folder contracts for shared infrastructure code (`infra/`) and reference baseline code (`baseline/`)

## Workflow Model

The default research loop is:

1. Architect proposes an idea and expected number of designs.
2. Designer writes one or more concrete `design.md` specs.
3. Reviewer audits design quality and feasibility.
4. Builder implements approved designs and runs sanity checks.
5. Reviewer audits implementation fidelity and correctness.
6. Orchestrator syncs statuses and submits eligible runs.
7. Results are summarized and shown in the dashboard.

This creates an auditable path from concept to execution.

## Repository Layout

- `agents/`
  Per-agent folders containing:
  - `prompt.md`: role-specific operating instructions
  - `memory.md`: persistent notes for that agent

- `scripts/`
  Automation engine and command-line surface:
  - `scripts/cli.py`: main entrypoint
  - `scripts/lib/`: shared logic modules
  - `scripts/slurm/`: scheduler-oriented helpers (customizable)
  - `scripts/tools/`: utility scripts (for example, design setup)

- `runs/`
  Tracking workspace for idea/design lifecycle and artifacts:
  - `runs/idea_overview.csv`
  - `runs/<idea_id>/design_overview.csv`
  - per-design directories and review files

- `baseline/`
  Canonical starting implementation used to bootstrap new designs.

- `infra/`
  Shared, stable code that should not frequently change across experiments.

- `docs/`
  Supporting documentation for pipeline behavior, statuses, and conventions.

- `website/`
  Generated dashboard output (`index.html`).

- `.automation.yaml`
  Central configuration for metrics, status rules, setup behavior, submit templates, and dashboard metadata.

## Configuration (`.automation.yaml`)

The automation behavior is controlled by these top-level sections:

- `results`
  - Which metrics to read from run outputs
  - How metrics files are discovered
  - Which paths are excluded

- `status`
  - Completion rule (for example, done epoch threshold)
  - Approval token used in review files

- `setup_design`
  - Which files are copied when creating a new design from a source
  - Destination code folder structure
  - Optional output-path patching behavior

- `submit`
  - Job-count command
  - Test/train submission command templates
  - Default submission limits

- `dashboard`
  - Repository URL metadata
  - Optional baseline-result tagging

## Core Commands

Run from repository root:

```bash
python scripts/cli.py summarize-results
python scripts/cli.py sync-status
python scripts/cli.py setup-design <src> <dst>
python scripts/cli.py submit-test <design_dir>
python scripts/cli.py submit-train <train_script> <job_name>
python scripts/cli.py submit-implemented
python scripts/cli.py build-dashboard
python scripts/cli.py deploy-dashboard
python scripts/cli.py update-all
```

## Typical Usage Pattern

1. Configure `.automation.yaml` for your project environment.
2. Update agent prompts in `agents/*/prompt.md` to match your domain and constraints.
3. Add/approve ideas and designs under `runs/`.
4. Use `setup-design` to bootstrap implementation from `baseline/` or an approved prior design.
5. Run sanity submissions and reviews.
6. Run `sync-status` regularly to keep trackers accurate.
7. Build/deploy dashboard as needed.

## Design Principles

- Explicit operations over hidden automation
- Strong separation of responsibilities between agents
- Reproducible experiment bookkeeping
- Minimal assumptions about model stack or runtime backend
- Easy migration across projects via configuration and prompt edits

## Notes

- This repository prefers manual/explicit command execution over background hooks.
- Status values should be updated through CLI sync logic, not manual CSV edits.
- Keep `baseline/` and `infra/` contracts clean: baseline evolves intentionally; infra stays stable unless shared behavior must change.
