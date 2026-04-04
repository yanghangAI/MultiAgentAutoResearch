#!/bin/bash
set -e

echo "1) Syncing all statuses..."
python scripts/tracker.py sync_all

echo "2) Running deployment script to update the dashboard..."
if [ -f "scripts/deploy_website.sh" ]; then
    ./scripts/deploy_website.sh
else
    echo "deploy_website.sh not found. Ensure it is executable."
fi

echo "✅ Sync and deploy complete!"
