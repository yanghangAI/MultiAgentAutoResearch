"""Training configuration for SapiensPose3D baseline.

Edit this file to change hyperparameters, paths, or training settings.
Fixed infrastructure constants (paths, splits, image size, etc.) live in infra.py.
"""

from infra import (
    BATCH_SIZE, ACCUM_STEPS, RANDOM_SEED,
    DATA_ROOT, PRETRAIN_CKPT, SPLITS_FILE,
    VAL_RATIO, TEST_RATIO, SINGLE_BODY_ONLY,
    IMG_H, IMG_W,
    NUM_WORKERS, LOG_INTERVAL, SAVE_INTERVAL, VAL_INTERVAL,
)


class _Cfg:
    # Paths
    data_root   = DATA_ROOT
    pretrain    = PRETRAIN_CKPT
    output_dir  = "/work/pi_nwycoff_umass_edu/hang/auto/runs/idea004/design001"
    resume      = ""

    # Model
    arch        = "sapiens_0.3b"
    img_h       = IMG_H
    img_w       = IMG_W
    head_hidden     = 256
    head_num_heads  = 8
    head_num_layers = 4
    head_dropout    = 0.1
    drop_path       = 0.1

    # Training
    epochs       = 20
    batch_size   = BATCH_SIZE
    num_workers  = NUM_WORKERS
    lr_backbone  = 1e-5
    lr_head      = 1e-4
    weight_decay = 0.03
    warmup_epochs= 3
    grad_clip    = 1.0
    accum_steps  = ACCUM_STEPS
    amp          = False  # M40 has no FP16 tensor cores
    patience     = 0

    # Loss weights
    lambda_depth = 0.1
    lambda_uv    = 0.2

    # Data splits
    splits_file      = SPLITS_FILE
    val_ratio        = VAL_RATIO
    test_ratio       = TEST_RATIO
    seed             = RANDOM_SEED
    single_body_only = SINGLE_BODY_ONLY
    max_train_seqs   = 0    # 0 = no cap
    max_val_seqs     = 0    # 0 = no cap

    # Logging / checkpoints
    log_interval  = LOG_INTERVAL
    save_interval = SAVE_INTERVAL
    val_interval  = VAL_INTERVAL
    max_batches   = 0
    no_scale_jitter = False


def get_config():
    return _Cfg()
