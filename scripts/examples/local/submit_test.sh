#!/bin/bash
# Example local test submission script.
# Runs a fast mini-train synchronously and captures output.
# Copy to scripts/local/submit_test.sh and adapt for your environment.
#
# Usage (called via .automation.yaml submit_test_command_template):
#   bash {root}/scripts/local/submit_test.sh {target_dir} {test_output}

set -e

TARGET_DIR=$(realpath "$1")
TEST_OUTPUT=$(realpath "$2")
mkdir -p "$TEST_OUTPUT"

# Resolve the training script (prefers code/ subdirectory)
if [ -f "$TARGET_DIR/code/train.py" ]; then
    TRAIN_PY="$TARGET_DIR/code/train.py"
elif [ -f "$TARGET_DIR/train.py" ]; then
    TRAIN_PY="$TARGET_DIR/train.py"
else
    echo "Error: no train.py found under $TARGET_DIR" >&2
    exit 1
fi

LOG_FILE="$TEST_OUTPUT/test.log"
echo "Running test train: $TRAIN_PY"
echo "Output: $LOG_FILE"

python "$TRAIN_PY" 2>&1 | tee "$LOG_FILE"
