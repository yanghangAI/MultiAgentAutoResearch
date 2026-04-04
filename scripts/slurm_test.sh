#!/bin/bash
#SBATCH --job-name=test_train
#SBATCH --partition=gpu
#SBATCH --constraint=1080ti
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=1
#SBATCH --mem=11G
#SBATCH --time=00:10:00

set -u

# The first argument is the design folder (containing code/ subfolder), defaults to current directory
TARGET_DIR=${1:-$PWD}
ROOT_DIR=$(dirname "$(dirname "$(realpath "$0")")")

cd "$TARGET_DIR/code" || exit 1

module load conda/latest
conda activate hang

echo "[test] Running train.py in $TARGET_DIR with 2 train seqs, 1 val seq, for 2 epochs."

export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

python - <<'PY'
import sys
import os

sys.path.insert(0, os.getcwd())
# Ensure the root auto/ path is in sys.path to find infra.py
sys.path.insert(0, "/work/pi_nwycoff_umass_edu/hang/auto")
import config
import train

# Override config directly on the class
config._Cfg.epochs = 2
config._Cfg.max_train_seqs = 2
config._Cfg.max_val_seqs = 1
config._Cfg.num_workers = 0  # prevent dataloader multiprocess issues in short runs
# output goes in the design folder (parent of code/), not inside code/
config._Cfg.output_dir = os.path.join(os.path.dirname(os.getcwd()), "test_output")

# Execute
train.main()
PY

echo "[test] Finished."