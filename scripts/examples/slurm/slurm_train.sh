#!/bin/bash
# Example SLURM training job script.
# Copy to scripts/slurm/slurm_train.sh and adapt for your environment.
#
# TODO: Update SBATCH directives for your cluster (partition, GPU type, memory, time).
# TODO: Update the conda/module activation commands for your environment.

#SBATCH --partition=gpu          # TODO: change to your partition
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=11G
#SBATCH --time=48:00:00
#SBATCH --output=slurm_%j.out

set -u

ROOT_DIR="$(dirname "$(dirname "$(dirname "$(realpath "$0")")")")"

# TODO: Activate your environment (conda, virtualenv, module load, etc.)
# module load conda/latest
# conda activate your_env_name

# IMPORTANT: Set PYTHONPATH to repo root so `import infra` works
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

# Resolve design directory for failure sentinel
SCRIPT_DIR=$(dirname "$TRAIN_PY")
if [ "$(basename "$SCRIPT_DIR")" = "code" ]; then
    DESIGN_DIR=$(dirname "$SCRIPT_DIR")
else
    DESIGN_DIR="$SCRIPT_DIR"
fi

# Run training; write training_failed.txt on non-zero exit
python "$TRAIN_PY" || {
    echo "Training exited with code $? at $(date)" > "$DESIGN_DIR/training_failed.txt"
    exit 1
}
