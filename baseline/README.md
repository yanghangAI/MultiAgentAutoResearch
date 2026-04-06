# Baseline Folder

Use this folder for the canonical baseline implementation.

Typical contents:
- baseline training entrypoint (for example `train.py`)
- baseline config/model/support files

Contract:
- This is the starting point for new design bootstraps.
- `python scripts/cli.py setup-design baseline/ <design_dir>` should copy from here.
