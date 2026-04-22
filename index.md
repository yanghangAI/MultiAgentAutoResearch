# Repository Index

One-line descriptions for every top-level entry in this folder.

## Documents

| Path | What it is |
|---|---|
| [`README.md`](README.md) | Main documentation — motivation, setup, CLI reference, configuration, integrity checks. |
| [`index.md`](index.md) | This file. Directory-level index for navigating the repository. |
| [`.automation.json`](.automation.json) | Project configuration — metric fields, status rules, submission commands, `integrity.immutable_paths`. |
| [`.gitignore`](.gitignore) | Git ignore patterns. |

## Agents (`agents/`)

Each agent has a `prompt.md` describing its role and a `memory.md` structured mistake log.

| Path | What it is |
|---|---|
| [`agents/Architect/`](agents/Architect) | Proposes new ideas or extends existing ones; always declares a starting point. |
| [`agents/Designer/`](agents/Designer) | Elaborates an idea into an implementable `design.md`. |
| [`agents/Reviewer/`](agents/Reviewer) | Semantic auditor — feasibility with cited code, algorithm fidelity, training-signal sanity. |
| [`agents/Builder/`](agents/Builder) | Implements designs in scope, quotes changed lines, runs sanity tests. |
| [`agents/Orchestrator/`](agents/Orchestrator) | Coordinates agents; the only role that spawns sub-agents. |
| [`agents/Debugger/`](agents/Debugger) | Fixes automation/infrastructure bugs reported by other agents. |

## Setup (`setup/`)

| Path | What it is |
|---|---|
| [`setup/Setup_Agent.md`](setup/Setup_Agent.md) | Main setup agent prompt — configures the framework for a new project. |
| [`setup/Infra_Baseline_Agent.md`](setup/Infra_Baseline_Agent.md) | Generates `infra/` (shared code) and `baseline/` (starting implementation). |
| [`setup/Prompt_Updater_Agent.md`](setup/Prompt_Updater_Agent.md) | Tailors agent prompts to the target project's vocabulary. |

## Code (`scripts/`)

| Path | What it is |
|---|---|
| [`scripts/cli.py`](scripts/cli.py) | Unified CLI entrypoint for all framework commands. |
| [`scripts/lib/`](scripts/lib) | Core modules: `scope`, `claims`, `memory`, `status`, `results`, `review`, `submit`, `dashboard`, `validate`, etc. |
| [`scripts/tools/`](scripts/tools) | Supporting tools (e.g. `setup_design.py`, diff helpers). |
| [`scripts/examples/`](scripts/examples) | Reference submission scripts for Slurm and local runners. |

## Training Artifacts

| Path | What it is |
|---|---|
| [`baseline/`](baseline) | Starting implementation — bootstrapped into every new design. |
| [`infra/`](infra) | Shared stable code (dataset utils, metrics, logging). Byte-locked by `integrity.immutable_paths`. |
| [`runs/`](runs) | Live experiment tracker. Every experiment lives at `runs/<idea_id>/<design_id>/`. |
| [`website/`](website) | Generated results dashboard (`index.html`). |

## Tests & Docs

| Path | What it is |
|---|---|
| [`tests/`](tests) | Test suite (pytest). Covers CLI, scope/claim integrity, taint propagation, memory hooks. |
| [`docs/`](docs) | Additional project-specific documentation. |
| [`memory/`](memory) | Cross-session memory storage (not agent memory — that lives under `agents/*/memory.md`). |

## Key Files Inside `runs/<idea_id>/<design_id>/`

| File | What it is |
|---|---|
| `design.md` | Concrete implementation spec, including `**Parent:**`. |
| `.parent` | Absolute path of the bootstrap source (`baseline/` or a prior design). Written by `setup-design`. |
| `implementation_summary.md` | Builder's change log; cites files and quotes key snippets. |
| `design_review.md` / `code_review.md` | Reviewer verdicts (APPROVED / REJECTED + strongest objection + evidence). |
| `scope_check.pass` / `scope_check.fail` | Result of `check-scope`. Descendants of any `.fail` are tainted. |
| `test_output/` | Outputs from the reduced test-train run. |
| `output/` | Outputs from the real training run. |
| `code/` | The actual implementation, bootstrapped from the parent. |
