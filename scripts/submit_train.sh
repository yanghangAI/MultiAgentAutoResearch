#!/bin/bash

# Ensure a path to the training python script was provided
if [ -z "${1:-}" ]; then
    echo "Usage: ./submit_train.sh <path_to_train_script> [idea_num-design_num]"
    echo "Example: ./submit_train.sh runs/idea002/design001/train.py 002-001"
    exit 1
fi

TRAIN_PY_PATH=$(realpath "$1")
CODE_FOLDER=$(dirname "$TRAIN_PY_PATH")
DESIGN_FOLDER=$(dirname "$CODE_FOLDER")

# Determine job name from argument or fallback to a default
JOB_NAME=${2:-"train_job"}

# Submit the SLURM job
sbatch \
    --job-name="$JOB_NAME" \
    --time=48:00:00 \
    -o "$DESIGN_FOLDER/slurm_%j.out" \
    --export=ALL,TRAIN_PY="$TRAIN_PY_PATH" \
    scripts/slurm_train.sh
