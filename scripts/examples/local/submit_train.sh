#!/bin/bash
# Example local training submission script.
# Runs training in the background with nohup.
# Copy to scripts/local/submit_train.sh and adapt for your environment.
#
# Usage (called via .automation.json submit_train_command_template):
#   bash {root}/scripts/local/submit_train.sh {train_script} {job_name}

set -e

TRAIN_PY=$(realpath "$1")
JOB_NAME="${2:-train_job}"

SCRIPT_DIR=$(dirname "$TRAIN_PY")
if [ "$(basename "$SCRIPT_DIR")" = "code" ]; then
    DESIGN_DIR=$(dirname "$SCRIPT_DIR")
else
    DESIGN_DIR="$SCRIPT_DIR"
fi

# IMPORTANT: Set PYTHONPATH to repo root so `import infra` works
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

LOG_FILE="$DESIGN_DIR/${JOB_NAME}.log"

echo "Launching training job '$JOB_NAME' in background..."
echo "  Script : $TRAIN_PY"
echo "  Log    : $LOG_FILE"

# Run training in background; write training_failed.txt on non-zero exit
nohup bash -c "python \"$TRAIN_PY\" > \"$LOG_FILE\" 2>&1 || echo 'Training exited with code '\$?' at '\$(date) > \"$DESIGN_DIR/training_failed.txt\"" &
echo "PID $! started."
