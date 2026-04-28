# Autonomous Research Pipeline (Generic)

## Agent Roles

1. Orchestrator
- Coordinates all stages.
- Spawns and routes work between sub-agents.
- Applies status updates through `scripts/cli.py sync-status`.

2. Architect
- Proposes new idea-level exploration directions.
- Defines expected number of designs in `idea.md`.

3. Designer
- Drafts detailed `design.md` specs for each variation.
- Defines explicit starting point path for each design.

4. Builder
- Implements one approved design spec at a time and exits after `review-check-implementation` passes.
- Does **not** run `submit-test` or wait for test results — the orchestrator runs the test, classifies pass/fail, and respawns Builder with the failure log on retry. See `docs/python_orchestrator.md`.

5. Reviewer
- Reviews designs and implementation quality.
- Writes explicit APPROVED/REJECTED decisions.

## Filesystem Contract

- Idea tracker: `runs/idea_overview.csv`
- Per-idea design tracker: `runs/<idea_id>/design_overview.csv`
- Idea spec: `runs/<idea_id>/idea.md`
- Design spec: `runs/<idea_id>/<design_id>/design.md`
- Review outputs: `design_review.md`, `code_review.md`

## Command-Driven Workflow

Use explicit commands rather than hooks/cron:

- `python scripts/cli.py summarize-results`
- `python scripts/cli.py sync-status`
- `python scripts/cli.py setup-design <src> <dst>`
- `python scripts/cli.py submit-test <design_dir>`
- `python scripts/cli.py submit-train <train_script> <job_name>`
- `python scripts/cli.py submit-implemented`
- `python scripts/cli.py build-dashboard`
- `python scripts/cli.py deploy-dashboard`
