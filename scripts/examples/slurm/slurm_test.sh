#!/bin/bash
# Example SLURM test job script.
# Copy to scripts/slurm/slurm_test.sh and adapt for your environment.
#
# TODO: Update SBATCH directives for your cluster (partition, GPU type, memory, time).
# TODO: Update the conda/module activation commands for your environment.
# TODO: Update the config override section to match your project's config structure.

#SBATCH --job-name=test_train
#SBATCH --partition=gpu          # TODO: change to your partition
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=1
#SBATCH --mem=11G
#SBATCH --time=00:10:00

set -u

# The first argument is the design folder (containing code/ subfolder)
TARGET_DIR=${1:-$PWD}
ROOT_DIR=$(dirname "$(dirname "$(dirname "$(realpath "$0")")")")

cd "$TARGET_DIR/code" || exit 1

# TODO: Activate your environment (conda, virtualenv, module load, etc.)
# module load conda/latest
# conda activate your_env_name

echo "[test] Running test train in $TARGET_DIR"

# IMPORTANT: Set PYTHONPATH to repo root so `import infra` works
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"
export ROOT_DIR

# TODO: Replace this section with your project's test train invocation.
# The test should run a minimal version of training (few epochs, small data)
# and write output to the test_output/ directory.
python train.py

echo "[test] Finished."
