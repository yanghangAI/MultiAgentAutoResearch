#!/bin/bash

# Configuration
MAX_JOBS=30

echo "--- Auto-Submit Triggered ---"

IMPLEMENTED_DESIGNS=()

while IFS= read -r csv_file; do
    IDEA_DIR=$(dirname "$csv_file")
    IDEA_ID=$(basename "$IDEA_DIR")
    
    # Use python to safely parse CSV and find 'Implemented' to avoid comma issues
    # Output format: IDEA_DIR/Design_ID
    while IFS= read -r d_id; do
        if [ -n "$d_id" ]; then
            IMPLEMENTED_DESIGNS+=("$IDEA_DIR/$d_id")
        fi
    done < <(python -c "
import csv, sys
from pathlib import Path
try:
    with open('$csv_file', 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if len(row) >= 3 and row[2].strip() == 'Implemented':
                print(row[0].strip())
except Exception as e:
    pass
")

done < <(find runs -name "design_overview.csv")

if [ ${#IMPLEMENTED_DESIGNS[@]} -eq 0 ]; then
    echo "No 'Implemented' designs found waiting for submission."
    exit 0
fi

# Submit jobs loop
for design_path in "${IMPLEMENTED_DESIGNS[@]}"; do
    # Count current jobs
    CURRENT_JOBS=$(squeue -u "$USER" -h | wc -l)
    
    if [ "$CURRENT_JOBS" -ge "$MAX_JOBS" ]; then
        echo "Job limit reached ($CURRENT_JOBS/$MAX_JOBS). Pausing submissions."
        break
    fi
    
    train_script="${design_path}/train.py"
    if [ ! -f "$train_script" ]; then
        echo "Warning: $train_script does not exist! Skipping."
        continue
    fi
    
    D_ID=$(basename "$design_path")
    I_ID=$(basename $(dirname "$design_path"))
    JOB_NAME="${I_ID}-${D_ID}"
    
    echo "Submitting training job for $JOB_NAME ($CURRENT_JOBS/$MAX_JOBS jobs running)..."
    ./scripts/submit_train.sh "$train_script" "$JOB_NAME"
    
done

echo "Syncing tracker statuses..."
python scripts/tracker.py sync_all
echo "Auto-Submit complete at: $(TZ='America/New_York' date '+%Y-%m-%d %H:%M:%S')"
