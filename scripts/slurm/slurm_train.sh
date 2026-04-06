#!/bin/bash
#SBATCH --partition=gpu
#SBATCH --constraint=1080ti
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=11G
#SBATCH --time=48:00:00
#SBATCH --output=slurm_%j.out

# Usage (called by run_trials.py):
#   sbatch --job-name=<idea_num>-<design_num> --time=48:00:00 -o <log_file> --export=ALL,TRAIN_PY=<path> scripts/slurm/slurm_train.sh

set -u

ROOT_DIR="$(dirname "$(dirname "$(dirname "$(realpath "$0")")")")"

module load conda/latest
conda activate hang

export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

python "$TRAIN_PY"
