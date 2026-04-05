#!/bin/bash
# Move to the workspace root directory so the script can find 'runs/'
cd "$(dirname "$0")/.." || exit

echo "=================================================="
echo "Run Started: $(TZ='America/New_York' date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="

echo "Running summarize_results.py..."
python scripts/summarize_results.py
echo "Done!"
