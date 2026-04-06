# Autonomous Research Pipeline

## The Agents

**1. Orchestrator (The Coordinator)**
* **Role:** The central manager of the entire research pipeline. It is the only entity allowed to spawn other sub-agents.
* **Responsibilities:** Delegates tasks sequentially, passes directory paths between agents (acting as a zero-overhead messenger), and manages the pipeline state. It determines when to spawn the Architect, Designer, Builder, or Reviewer based on the current filesystem state and tracker statuses.

**2. Architect (The Ideation Lead)**
* **Role:** The high-level researcher defining the structural search space.
* **Responsibilities:** Reflects on past experiments via `results.csv`, conceptualizes novel design axes or architectural changes (ensuring they fit within a 20-epoch 1080ti budget), and decides how many detailed variations to explore per idea.

**3. Designer (The Technical Draftsman)**
* **Role:** The detail-oriented blueprint creator.
* **Responsibilities:** Takes the Architect's broad ideas and writes exact, mathematically sound, implementable configuration variations (saved to `design.md`). Explicitly defines the starting point (e.g., a previous design or the baseline) and all experimental hyperparameters.

**4. Builder (The Software Engineer)**
* **Role:** The PyTorch implementation layer.
* **Responsibilities:** Takes a finalized `design.md` and writes/modifies the Python training loop (`train.py`) to match it. It is responsible for making sure the code runs by executing local 2-epoch test runs (`python scripts/cli.py submit-test <design_dir>`) to ensure there are no immediate code/OOM crashes before requesting a code review.

**5. Reviewer (The Strict Gatekeeper)**
* **Role:** The dedicated auditor for both designs and code.
* **Responsibilities:** Replaces the review overhead previously handled by the Architect and Designer. 
  - *Design Review:* Evaluates a drafted `design.md` against mathematical feasibility and the 11GB VRAM budget.
  - *Code Review:* Evaluates the Builder's `train.py` and `config.py` to ensure they strictly implement the specifications defined in `design.md` with no hardcoded shortcuts.

---

## Infrastructure Automation (Hooks & Crontab)

To eliminate the need for an LLM to actively wait for jobs to finish or manually manage Slurm submissions (the old "Runner" bottleneck), the system uses background "fire-and-forget" automation. The LLM's job ends the moment the Reviewer approves the code. The system infrastructure handles the rest based on Linux `flock` concurrency protections.

**1. Agent Hooks (Post-Action Automation)**
* **What it does:** Every time an agent finishes a step (e.g., writes a file), the agent framework (like Claude Code) triggers a local background bash hook.
* **Scripts executed:** `python scripts/cli.py sync-status && python scripts/cli.py submit-implemented`
* **Purpose:** Immediately syncs `design_overview.csv` with the filesystem reality. If the Reviewer just approved a code implementation, `sync-status` marks it "Implemented". Then, `submit-implemented` instantly sweeps the CSVs, finds the newly "Implemented" design, and submits it to SLURM (capping at 30 concurrent jobs) before the agent even takes its next breath.

**2. The Crontab (Periodic Cluster Synchronization)**
* **What it does:** A scheduled Linux daemon running every 15 minutes in the background.
* **Scripts executed:** `python scripts/cli.py summarize-results && python scripts/cli.py sync-status && python scripts/cli.py submit-implemented`
* **Purpose:** The bridge between the disconnected SLURM cluster and the tracked CSV state. Since the LLM agents do not wait for the 48-hour trainings to finish, the Cron Job wakes up periodically to extract final MPJPE metrics from completed runs, writes them to `results.csv`, marks the designs as `Done`, and backfills the cluster queue with any pending `Implemented` jobs.

**3. Git Hooks (`post-commit`)**
* **What it does:** Triggers on any `git commit`. 
* **Scripts executed:** `python scripts/cli.py update-all` (triggering generation of `website/index.html` and deployment).
* **Purpose:** Ensures the frontend UX tracking dashboard hosted on `gh-pages` is always perfectly synchronized with the repository's main branch data.

---

## The Working Pipeline

1. **Ideation:** The **Orchestrator** spawns the **Architect**, who proposes a new research 'Idea' based on past results and states how many variations to explore.
2. **Drafting:** The Orchestrator delegates the idea to the **Designer**, who writes specific math and parameter configurations for a variation (`design.md`).
3. **Design Review:** The Orchestrator passes the `design.md` path to the **Reviewer**. If rejected, it goes back to the Designer. If approved, the design is officially accepted. The automated Agent Hook runs `sync-status`, marking it "Not Implemented," allowing the Designer to move on to the next variation.
4. **Implementation:** The Orchestrator spawns the **Builder** to tackle an approved design. It writes `train.py` and actively runs a 2-epoch sanity test (`python scripts/cli.py submit-test <design_dir>`).
5. **Code Audit:** The Builder asks the Orchestrator for a review. The Orchestrator spawns the **Reviewer** to check `train.py` against `design.md`. If approved, the agent hook runs `sync-status` and immediately fires `submit-implemented`, putting the job in the SLURM queue.
6. **Execution (Asynchronous):** The AI agents move on to new tasks. Behind the scenes, the **Crontab** monitors the jobs. Once training completes, the Crontab pulls the metrics, updates the tracker to `Done`, and frees up the queue slot.
