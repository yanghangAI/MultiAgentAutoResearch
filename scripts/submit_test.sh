#!/bin/bash

# Target directory defaults to current directory if not provided
TARGET_DIR=${1:-$PWD}

# Create the output directory inside the target directory before submitting
mkdir -p "$TARGET_DIR/test_output"

# Submit the slurm job and override the output log path dynamically
sbatch -o "$TARGET_DIR/test_output/slurm_test_%j.out" scripts/slurm_test.sh "$TARGET_DIR"
