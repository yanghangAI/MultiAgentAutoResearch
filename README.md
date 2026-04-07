# Multi-Agent Auto Research

Run iterative ML experiments with AI agents handling the entire research loop — from proposing ideas to submitting jobs to publishing results.

You bring a training codebase. The agents handle the rest.

> Beta: this project is still actively updated and improved. If you run into questions, bugs, or confusing behavior, please open a GitHub issue.

---

## Demo

**[AutoSapiens](https://yanghangai.github.io/autosapiens/)** — a live example of this framework applied to human pose estimation research on the [Sapiens](https://github.com/facebookresearch/sapiens) model.

The agents autonomously explored 5 research directions (RGB-D fusion, kinematic attention masking, curriculum loss weighting, layer-wise learning rate decay, depth-aware positional embeddings) across 20+ design variants. The best result — layer-wise learning rate decay — reduced validation MPJPE from 142.5 to ~130, a ~9% improvement over baseline.

---

## Why Multi-Agent?

The core motivation is **context window limits**. A single agent running a full research campaign — reading all past results, the entire codebase, the current design, and its implementation — quickly exhausts its context. As the experiment count grows, a single agent becomes unusable.

Splitting the loop into specialized agents keeps each agent's context small and focused: the Architect reads only results summaries, the Designer reads one `idea.md`, the Builder reads one `design.md` plus relevant code. The CSV/file-based state store acts as external memory that persists across sessions. This makes the framework unbounded in campaign length — you can run hundreds of experiments without any single agent's context growing with the experiment count.

A second key feature is the **script layer**. Rather than relying on agents to track state in memory, every meaningful action — registering an idea, syncing statuses, submitting jobs, building the dashboard — is committed to disk through CLI scripts. This makes the system reliable: if an agent crashes or a session ends, no work is lost. The next agent picks up exactly where the last one left off by reading the files.

---

## What It Does

ML research is repetitive: come up with an idea, implement it, run it, check results, repeat. This framework delegates that loop to a team of AI agents that collaborate through a structured workflow:

```
┌─────────────────────── Orchestrator ───────────────────────────┐
│                                                                │
│  Architect → Designer → Reviewer → Builder → Reviewer          │
│      ↑                  (design)              (code)           │
│      │                                           │             │
│      └──────────── results from training ─────── submit jobs ──┘
└────────────────────────────────────────────────────────────────┘
                          Debugger (on-call for automation bugs)
```

Each agent has a focused role:

| Agent | What it does |
|---|---|
| **Architect** | Reads prior results, proposes new experiment ideas |
| **Designer** | Writes concrete implementation specs (`design.md`) |
| **Reviewer** | Approves or rejects designs and implementations |
| **Builder** | Implements approved designs, runs sanity tests |
| **Orchestrator** | Coordinates agents and runs orchestration-only scripts |
| **Debugger** | Fixes unexpected automation or execution bugs reported by other agents |

Experiment state is tracked in plain CSV files under `runs/`. The CLI keeps everything in sync.

---

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/yanghangAI/MultiAgentAutoResearch.git
cd MultiAgentAutoResearch
```

No dependencies beyond the Python standard library (plus `pytest` to run tests).

### 2. Run the Setup Agent

Open Claude Code in this repository. Enable **bypass mode** (ask claude to do it for you) so the agent can read and write files without interruption.

Then tell it to act as the Setup Agent:

> Read `setup/Setup_Agent.md` and act as the Setup Agent.

Claude Code will take it from there. The Setup Agent:
- Reads your training code to understand metrics, config, and runtime environment
- Asks you clarifying questions if anything is ambiguous
- Configures `.automation.yaml` for your project
- Writes and tests `infra/` (shared utilities) and `baseline/` (starting implementation)
- Updates all agent prompts with your project's vocabulary and conventions
- Validates the full pipeline end-to-end before handing off

After setup finishes, close that setup session and open a new Claude Code session before starting the Orchestrator.

### 3. Start the research loop

In a new Claude Code session, tell it to act as the Orchestrator:

> Read `agents/Orchestrator/prompt.md` and act as the Orchestrator. Start the research loop.

The Orchestrator spawns the Architect, which reads prior results and proposes ideas. From there the loop runs autonomously — designing, implementing, reviewing, submitting — and surfaces results in the dashboard.

---

## Day-to-Day Usage

Once set up, you interact with the framework at two levels:

**Let agents run the loop** — spawn the Orchestrator when you want new experiments. It coordinates everything.

**Run CLI commands when you need a manual sync:**

```bash
# Register a new idea explicitly
python scripts/cli.py add-idea idea001 "Layer-wise LR Decay"

# Register a new design explicitly
python scripts/cli.py add-design idea001 design001 "Depth-aware positional embeddings"

# Run lightweight structure checks before review
python scripts/cli.py review-check runs/idea001/idea.md

# After training outputs change — update all statuses
python scripts/cli.py sync-status

# When you want to submit all ready designs
python scripts/cli.py submit-implemented

# Rebuild and publish the results dashboard
python scripts/cli.py update-all
```

**Bootstrap a new design manually:**

```bash
# Copy baseline into a new design folder
python scripts/cli.py setup-design baseline/ runs/idea001/design002/
```

**Check results:**

```bash
python scripts/cli.py summarize-results   # aggregates metrics.csv → results.csv
python scripts/cli.py build-dashboard     # generates website/index.html
```

---

## Configuration

All behavior is controlled by `.automation.yaml`. The key fields:

```json
{
  "results": {
    "metric_fields": ["train_loss", "val_loss"],
    "primary_metric": "val_loss",
    "metrics_glob": "**/metrics.csv"
  },
  "status": {
    "done_epoch": 100
  },
  "submit": {
    "submit_train_command_template": "{root}/scripts/slurm/submit_train.sh {train_script} {job_name}"
  },
  "dashboard": {
    "github_repo_url": "https://github.com/your-org/your-repo"
  }
}
```

The Setup Agent fills this in for you. You only need to touch it if your project's metrics or compute environment changes.

---

## Repository Layout

```
agents/           AI agent prompts and memory
  Orchestrator/
  Architect/
  Designer/
  Reviewer/
  Builder/
  Debugger/
baseline/         Starting implementation — bootstrapped into every new design
infra/            Shared stable code (dataset utils, metrics, logging)
runs/             Live experiment tracker (ideas, designs, statuses)
scripts/
  cli.py          Main CLI entrypoint
  lib/            Core automation modules
  slurm/          HPC job submission scripts
setup/            Agent prompts for initial project setup
website/          Generated results dashboard
.automation.yaml  Project configuration
```

Within `runs/`, every experiment follows an **idea → design** lifecycle:

```
runs/
  idea_overview.csv              ← all ideas and their status
  idea001/
    idea.md                      ← what to explore and why
    design_overview.csv          ← all designs under this idea
    design001/
      design.md                  ← concrete implementation spec
      design_review.md           ← Reviewer design decision (APPROVED / REJECTED)
      code_review.md             ← post-implementation code audit
      test_output/               ← outputs from the reduced test-train run
      output/                    ← outputs from the real training run (project-specific)
      code/                      ← actual implementation (bootstrapped by setup-design)
```

Statuses are derived automatically from filesystem signals — review files, training outputs, job logs. Never edit CSVs by hand; run `sync-status` instead.
If you create a new `runs/ideaXXX/idea.md`, include `**Idea Name:** ...` so `sync-status` can auto-register it in `runs/idea_overview.csv`.
If you create a new `runs/<idea_id>/designXXX/design.md`, include `**Design Description:** ...` so `sync-status` can auto-register it in `runs/<idea_id>/design_overview.csv`.

**Design lifecycle:**

```
Not Implemented → Implement Failed
Not Implemented → Implemented → Submitted → Training → Done
```

**Idea lifecycle** (derived from its designs):

```
Not Designed → Designed → Implemented → Training → Done
```

---

## All CLI Commands

```bash
python scripts/cli.py add-idea <idea_id> <idea_name> # register a new idea
python scripts/cli.py add-design <idea_id> <design_id> <description> # register a new design
python scripts/cli.py review-check <target> # quick idea/design structure checks
python scripts/cli.py sync-status              # derive and update all statuses
python scripts/cli.py summarize-results        # aggregate metrics into results.csv
python scripts/cli.py setup-design <src> <dst> # bootstrap a new design from a source
python scripts/cli.py submit-test <design_dir> # submit a sanity test job
python scripts/cli.py submit-implemented       # submit all Implemented designs
python scripts/cli.py build-dashboard          # generate website/index.html
python scripts/cli.py deploy-dashboard         # push dashboard to gh-pages
python scripts/cli.py update-all               # sync + build + deploy in one step
```
