# Sapiens-RGBD 3D Pose Estimation — Baseline

Fine-tuning the [Sapiens](https://about.meta.com/research/sapiens/) 0.3B vision transformer on BEDLAM2 for single-person 3D pose estimation from RGB-D images.

## Project Structure

```
auto/
├── baseline.py                  # Forwarding stub — re-exports from baseline/
├── baseline/
│   ├── config.py                # Experiment config (_Cfg, get_config) — edit this per experiment
│   ├── train.py                 # LR schedule and training loop
│   ├── model.py                 # Backbone, head, weight loading
│   └── transforms.py            # Data transforms & augmentation
├── infra.py                     # Fixed constants, splits, logging, visualization — never modified between experiments
├── splits_rome_tracking.json    # Train/val split: 100/50 seqs from rome_tracking scene
└── runs/
    └── baseline/                # Training output
        ├── train_snapshot.py    # Copy of train.py saved at run start
        ├── metrics.csv          # Per-epoch train/val metrics
        ├── tb/                  # TensorBoard logs
        └── slurm_<jobid>.out    # SLURM stdout
```

## Model

### Backbone — `SapiensBackboneRGBD`
- **Architecture**: Sapiens 0.3B (ViT-Base variant, ~300M params)
- **Input**: 4-channel RGBD tensor `(B, 4, 640, 384)`
- **Pretrain**: Sapiens RGB MAE checkpoint (`sapiens_0.3b_epoch_1600_clean.pth`)
- **4th channel init**: depth patch embed weights = mean of the 3 RGB channel weights
- **Positional embedding**: bicubic-interpolated from 64×64 → 40×24 (H/16 × W/16)

### Head — `Pose3DHead` (Transformer Decoder)
- **Architecture**: Learnable joint queries cross-attending to backbone spatial features
- **Input projection**: `Linear(1024 → 256)` — projects backbone tokens to hidden dim
- **Joint queries**: `Embedding(70, 256)` — one learnable query per joint
- **Decoder**: 4× `TransformerDecoderLayer` (pre-norm, 8 heads, FFN=1024, dropout=0.1)
- **Output**: `Linear(256 → 3)` per joint → `(B, 70, 3)` joint positions

```
Backbone (ViT)  →  (B, 1024, 40, 24)
  input_proj    →  (B, 960, 256)       ← flattened spatial tokens (memory)
  + Embedding   →  (B, 70, 256)        ← joint queries
  TransformerDecoder × 4
  joints_out    →  (B, 70, 3)          ← root-relative 3D joint positions (metres)
```

**Total parameters**: 308.8M (293 backbone + 77 head tensors)

## Data

### Dataset — BEDLAM2subset
- **Path**: `/work/pi_nwycoff_umass_edu/hang/BEDLAM2subset`
- **Format**: per-person NPZ label files + JPEG frames + depth NPY arrays
- **Total clips**: 66 across ~45 scene types; 22,694 sub-sequences total
- **Depth-available clips**: 9 clips, 2,474 sub-sequences

### Splits — `splits_rome_tracking.json`
- **Scene**: `20241213_1_250_rome_tracking` (only depth-available scene used)
- **Train**: 100 sequences → 6,314 frames
- **Val**: 50 sequences → 3,316 frames
- **Seed**: 2026 (reproducible shuffle)
- **Verified**: 0 overlapping sequences, all pass data quality filters

### Transforms (train = val, no augmentation)
```
CropPerson   →  crop to person bbox, pad & resize to (640, 384)
SubtractRoot →  subtract pelvis position → root-relative joint coords
ToTensor     →  RGB: /255 → ImageNet normalize (mean/std)
                Depth: clip [0, 10m] / 10.0 → [0, 1]
```

### Per-frame Filters (in `BedlamFrameDataset.__getitem__`)
| Filter | Threshold | Source |
|--------|-----------|--------|
| Minimum bbox size | < 32px | — |
| Far-person (depth axis) | all joints ≥ 10m | matches sapiens/pose |
| Out-of-bounds joints | ≥ 50% outside image | matches sapiens/pose |
| Min visible joints | < 8 in-frame | matches sapiens/pose |

## Training


### Loss
Smooth L1 (β=0.05 m) on **body joints only** (joints 0–21, pelvis → wrists):
```python
loss = smooth_l1(pred[:, BODY_IDX], target[:, BODY_IDX], beta=0.05)
```
Depth and UV auxiliary losses removed. Hand/face joints excluded.

### LR Schedule
Cosine decay with linear warmup:
- Warmup: epochs 0–3, linear ramp from 0 → base LR
- Decay: cosine from base LR → 0 over remaining epochs

### Metric
**MPJPE** (Mean Per Joint Position Error) in mm, evaluated on body joints only.

## Design Notes

- **`baseline.py`**: all experimentally-changeable code — model, loss, augmentation, hyperparameters
- **`infra.py`**: stable utilities never modified between experiments — constants, split logic, CSV logger, visualization, checkpoint helpers
- **No checkpoints saved** in the baseline run (disabled to reduce I/O overhead during testing)

## Automation Scripts

The experiment automation and dashboard tooling now live under:

- [`scripts/README.md`](/work/pi_nwycoff_umass_edu/hang/auto/scripts/README.md)

That guide covers:

- the unified `python scripts/cli.py ...` command surface
- the shared modules in `scripts/lib/`
- compatibility wrappers for older shell entrypoints
- dashboard build and deploy workflow
- script-layer test coverage
