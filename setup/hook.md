# Manual Script Workflow

This repository no longer recommends automatic git hooks, post-write hooks, or background file watchers for the experiment pipeline.

Instead, invoke the script tooling explicitly when the workflow reaches the appropriate step.

Recommended manual commands:

```bash
python scripts/cli.py summarize-results
python scripts/cli.py sync-status
python scripts/cli.py submit-implemented
python scripts/cli.py build-dashboard
python scripts/cli.py deploy-dashboard
python scripts/cli.py update-all
```

Recommended usage pattern:

1. After review files or training outputs change, run:
   ```bash
   python scripts/cli.py sync-status
   ```
2. When you are ready to submit pending implemented designs, run:
   ```bash
   python scripts/cli.py submit-implemented
   ```
3. When you want to rebuild and deploy the dashboard, run:
   ```bash
   python scripts/cli.py update-all
   ```

If you still want periodic automation in the future, prefer a deliberate cron job over edit-time or commit-time hooks.
