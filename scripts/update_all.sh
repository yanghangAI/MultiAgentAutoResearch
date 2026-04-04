#!/bin/bash
set -e

echo "1) Updating results..."
./scripts/run_summarize.sh

echo "2) Syncing all statuses..."
python scripts/tracker.py sync_all

echo "3) Running deployment script to update the dashboard..."
if [ -f "scripts/deploy_website.sh" ]; then
    ./scripts/deploy_website.sh
else
    echo "deploy_website.sh not found. Ensure it is executable."
    exit 1
fi

echo "✅ All updates (results -> status -> website) and deploy complete!"
