# Multi-Agent Auto Research

A reusable multi-agent automation framework for research and ML experiments. Provides a consistent operating model for running iterative experiments end to end: define ideas, draft design variants, implement and review changes, submit runs, track status, summarize results, and publish a dashboard.

The system is **project-agnostic** — adapt behavior via `.automation.yaml` and agent prompts rather than rewriting the automation core.

## Workflow

```
Architect → Designer → Reviewer → Builder → Reviewer → Orchestrator (submit)
```

1. **Architect** proposes an idea and expected number of designs.
2. **Designer** writes one or more concrete `design.md` specs.
3. **Reviewer** audits design quality and feasibility.
4. **Builder** implements approved designs and runs sanity checks.
5. **Reviewer** audits implementation fidelity and correctness.
6. **Orchestrator** syncs statuses and submits eligible runs.
7. Results are summarized and shown in the dashboard.

## Repository Layout

```
agents/          Per-agent prompt.md and memory.md
baseline/        Canonical starting implementation for new design bootstraps
infra/           Shared stable code (dataset utils, metrics, logging)
runs/            Experiment tracking workspace
  idea_overview.csv
  <idea_id>/
    idea.md
    design_overview.csv
    <design_id>/
      design.md
      review.md / code_review.md
scripts/         Automation CLI and shared logic
  cli.py         Main entrypoint
  lib/           Core modules
  slurm/         HPC job submission helpers
  tools/         Utility scripts (setup-design, etc.)
website/         Generated dashboard (index.html)
.automation.yaml Central configuration
```

## Setup

Setup is handled by the **Setup Agent** (`setup/Setup_Agent.md`). Spawn it and give it one thing:

- **Path to your project directory**

The Setup Agent explores the project, writes a structured overview to `docs/project_overview.md`, then spawns two specialist sub-agents in parallel:

- **Prompt Updater** (`setup/Prompt_Updater_Agent.md`) — adapts all agent prompts to the target project's vocabulary, metrics, and file conventions.
- **Infra and Baseline Builder** (`setup/Infra_Baseline_Agent.md`) — writes, tests, and documents `infra/` and `baseline/` code.

The Setup Agent then validates the full pipeline end-to-end and hands off. If anything is ambiguous, it asks you directly before proceeding.

## Core Commands

```bash
python scripts/cli.py sync-status              # sync idea/design statuses from filesystem signals
python scripts/cli.py summarize-results        # aggregate metrics.csv files into results.csv
python scripts/cli.py setup-design <src> <dst> # bootstrap a new design from baseline or a prior design
python scripts/cli.py submit-test <design_dir> # submit a sanity test job
python scripts/cli.py submit-implemented       # submit all Implemented designs for full training
python scripts/cli.py build-dashboard          # generate website/index.html
python scripts/cli.py deploy-dashboard         # push dashboard to gh-pages branch
python scripts/cli.py update-all               # sync + build + deploy in one step
```

## Status Model

Statuses are derived automatically by `sync-status` — never edit CSVs by hand.

**Design statuses** (in progression):

| Status | Meaning |
|---|---|
| `Not Implemented` | Design approved, implementation not ready |
| `Implemented` | Code approved, ready for full submission |
| `Submitted` | Job submitted, metrics not yet present |
| `Training` | Metrics present, completion criterion not reached |
| `Done` | Completion criterion reached (`status.done_epoch`) |

**Idea statuses** are derived from the aggregate of its designs:

| Status | Meaning |
|---|---|
| `Not Designed` | Expected designs not fully drafted/approved |
| `Designed` | All designs exist, implementation not complete |
| `Implemented` | All designs at least implemented |
| `Training` | All designs in training/done |
| `Done` | All designs done |

## Design Principles

- Explicit CLI operations over hidden automation or hooks
- Strong separation of responsibilities between agents
- Reproducible experiment bookkeeping
- Minimal assumptions about model stack or compute backend
- Easy migration across projects via config and prompt edits only
