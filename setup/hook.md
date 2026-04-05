# System Hooks & Automation Triggers

To completely remove administrative overhead from the LLM agents, the pipeline's deterministic scripts should be bound to event hooks. 

This document defines exactly **what** scripts should run and **when** they should be triggered.

## 1. Agent Hooks (e.g., Claude Code `post_command`, or Master Loop Wrapper)
**Trigger:** Fires immediately after an agent completes a task (e.g., finishes writing `design.md`, completes writing `train.py`, or saves a `code_review.md`).
**Scripts to Run:**
```bash
python scripts/tracker.py sync_all
./scripts/auto_submit.sh
```
* **Why:** The moment an agent finishes evaluating or writing code, the system must parse the new files, update `design_overview.csv` to its true state (e.g., `Not Implemented` -> `Implemented`), and automatically submit any freshly approved jobs to SLURM. 

## 2. Git Hooks (`post-commit`)
**Trigger:** Fires locally whenever a `git commit` is successfully created.
**Scripts to Run:**
```bash
./scripts/update_all.sh
```
*(Note: `update_all.sh` should internally call `run_summarize.sh`, `tracker.py`, `generate_website.py`, and `deploy_website.sh`)*
* **Why:** If you or an agent commits a batch of finalized designs or training scripts to the `main` branch, the hook will ensure that the static website dashboard is generated and pushed to the `gh-pages` branch seamlessly.

## 3. Scheduled System Hooks (`cron` or `systemd` timers)
**Trigger:** Fires asynchronously strictly on a timer (e.g., every 15 or 30 minutes).
**Scripts to Run:**
```bash
./scripts/run_summarize.sh
python scripts/tracker.py sync_all
./scripts/auto_submit.sh
```
* **Why:** SLURM jobs finish unpredictably in the background. A time-based hook guarantees that when a 24-hour training job wraps up, `run_summarize.sh` pulls its final metrics into `results.csv`, `tracker.py` updates the design's status from `Training` to `Done`, and `auto_submit.sh` claims the newly freed SLURM node slot for the next queued job.

---

### Summary of Script Responsibilities
- **`scripts/tracker.py sync_all`**: The universal truth-maker. Run this anytime a file changes or a SLURM job finishes.
- **`scripts/auto_submit.sh`**: The queue manager. Run this anytime statuses change so it can keep the cluster fed (up to the 30-job limit).
- **`scripts/run_summarize.sh`**: The data scraper. Run this periodically to harvest metrics from completed SLURM output folders.
- **`scripts/deploy_website.sh`**: The UI publisher. Run this only when you want to update the public-facing HTTP dashboard.