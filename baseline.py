"""Forwarding stub — baseline has been split into baseline/.

    baseline/config.py     — training configuration (_Cfg, get_config)
    baseline/transforms.py — data transforms & augmentation
    baseline/model.py      — backbone, head, weight loading
    baseline/train.py      — LR schedule, training loop, main()

To run the baseline:  python scripts/cli.py submit-train baseline/train.py baseline
To test the baseline: python scripts/cli.py submit-test baseline
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "baseline"))
from config import _Cfg, get_config  # noqa: F401
from train import get_lr_scale, train_one_epoch, main  # noqa: F401

if __name__ == "__main__":
    main()
