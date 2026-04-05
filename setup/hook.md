# Agent Instructions: Setup System Hooks

If you are an AI agent and the user asks you to "setup the hooks", immediately perform the following three steps without asking for clarification:

### Step 1: Create Git Post-Commit Hook
Create the file `.git/hooks/post-commit` with this exact content:
```bash
#!/bin/bash
if [ "$_IN_POST_COMMIT" = "1" ]; then exit 0; fi
export _IN_POST_COMMIT=1

if [ -f "scripts/update_all.sh" ]; then
    ./scripts/update_all.sh
fi
```
Then, run `chmod +x .git/hooks/post-commit` in the terminal to make it executable.

### Step 2: Configure Agent Post-Command Hook
Append the following instruction to `.claude/CLAUDE.md` (or your specific agent system memory/prompt file):
```text

## Post-Action Hook
Immediately after completing any file modification, code writing, or review task, you must run the following bash command:
`python scripts/tracker.py sync_all && ./scripts/auto_submit.sh`
```

### Step 3: Print Cron Job Instructions
You cannot edit the user's crontab directly. Send a direct message to the user containing exactly this text:

```text
Your Git post-commit hook and agent post-action hooks are successfully configured!
To set up the periodic scheduled hook for the SLURM cluster, please run `crontab -e` in your terminal and add this line:
*/15 * * * * cd /work/pi_nwycoff_umass_edu/hang/auto && ./scripts/run_summarize.sh && python scripts/tracker.py sync_all && ./scripts/auto_submit.sh
```
