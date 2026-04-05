# Agent Instructions: Setup System Hooks

If you are an AI agent and the user asks you to "setup the hooks", immediately perform the following three steps without asking for clarification:

### Step 1: Create Git Post-Commit Hook
Create the file `.git/hooks/post-commit` with this exact content:
```bash
#!/bin/bash
if [ "$_IN_POST_COMMIT" = "1" ]; then exit 0; fi
export _IN_POST_COMMIT=1

if [ -f "scripts/update_all.sh" ]; then
    flock -w 300 /tmp/sapiens_pipeline.lock -c "./scripts/update_all.sh"
fi
```
Then, run `chmod +x .git/hooks/post-commit` in the terminal to make it executable.

### Step 2: Configure Automatic Post-File-Write Hook

**Goal:** After every file write or edit, automatically run a concurrency-safe wrapper:
```bash
cd /work/pi_nwycoff_umass_edu/hang/auto && flock -n /tmp/sapiens_pipeline.lock -c "python scripts/tracker.py sync_all && ./scripts/auto_submit.sh" 2>/dev/null || true
```

This must be triggered by the agent harness/runtime — not by the agent itself — so it fires reliably regardless of agent behavior.

Use whichever mechanism your agent CLI supports:

**Claude Code** — add to `.claude/settings.json` (merge with existing, do not replace):
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "cd /work/pi_nwycoff_umass_edu/hang/auto && flock -n /tmp/sapiens_pipeline.lock -c \"python scripts/tracker.py sync_all && ./scripts/auto_submit.sh\" 2>/dev/null || true",
            "statusMessage": "Syncing tracker and submitting..."
          }
        ]
      }
    ]
  }
}
```
Validate with:
```bash
jq -e '.hooks.PostToolUse[] | select(.matcher == "Write|Edit") | .hooks[] | select(.type == "command") | .command' .claude/settings.json
```

**Cursor / other agent CLIs** — configure a post-file-save or post-tool-use hook in that tool's settings to run the same command above after any file modification.

**No native hook support** — fall back to a filesystem watcher:
```bash
# Run in background; watches for file changes and triggers the sync
while inotifywait -r -e close_write /work/pi_nwycoff_umass_edu/hang/auto --exclude '\.git'; do
    cd /work/pi_nwycoff_umass_edu/hang/auto && flock -n /tmp/sapiens_pipeline.lock -c "python scripts/tracker.py sync_all && ./scripts/auto_submit.sh"
done
```

### Step 3: Print Cron Job Instructions
You cannot edit the user's crontab directly. Send a direct message to the user containing exactly this text:

```text
Your Git post-commit hook and agent post-action hooks are successfully configured!
To set up the periodic scheduled hook for the SLURM cluster, please run `crontab -e` in your terminal and add this line:
0 * * * * cd /work/pi_nwycoff_umass_edu/hang/auto && flock -w 300 /tmp/sapiens_pipeline.lock -c "./scripts/run_summarize.sh && python scripts/tracker.py sync_all && ./scripts/auto_submit.sh" >> /work/pi_nwycoff_umass_edu/hang/auto/cron_hook.log 2>&1
```
