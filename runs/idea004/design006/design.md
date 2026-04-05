# Design 006 — Constant Decay LLRD (gamma=0.85, unfreeze_epoch=10)

## Overview

This design applies Layer-Wise Learning Rate Decay (LLRD) to the Sapiens ViT-B backbone with the steepest decay factor in the grid, `gamma=0.85`, and the latest unfreezing point, `unfreeze_epoch=10`. It tests the most conservative shallow-layer update schedule in idea004.

## Problem

Same as the other idea004 designs: prevent catastrophic forgetting of shallow pre-trained ViT features while allowing the deeper layers to adapt to depth-aware 3D pose estimation.

## Architecture

- Backbone: Sapiens ViT-B (`sapiens_0.3b`), 24 transformer blocks (0-23)
- Head: Transformer decoder with 4 layers, unchanged from the baseline
- No new parameters introduced

## LLRD Formula

For block index `i` from 0 to 23:

```text
lr_i = base_lr_backbone * gamma^(23-i)
```

Where:
- `base_lr_backbone = 1e-4`
- `gamma = 0.85`
- `num_blocks = 24`

Reference values:
- Block 23: `1e-4`
- Block 22: `8.5e-5`
- Block 11: `~1.422e-5`
- Block 0: `~2.096e-6`
- Patch+pos embedding: `1e-4 * 0.85^24 ~ 1.781e-6`

## Progressive Unfreezing

- Epochs 0-9: freeze blocks 0-11 plus patch/pos embeddings
- Epoch 10+: unfreeze all backbone parameters and rebuild the optimizer with the full 26-group LLRD layout
- `weight_decay = 0.03`
- Apply the existing cosine LR scale to the rebuilt optimizer at epoch 10

## Config Summary

| Parameter | Value |
|---|---|
| gamma | 0.85 |
| base_lr_backbone | 1e-4 |
| lr_head | 1e-4 |
| unfreeze_epoch | 10 |
| weight_decay | 0.03 |
| epochs | 20 |
| warmup_epochs | 3 |

## Rationale

- This is the strongest regularization point in the idea004 grid.
- It should preserve shallow pre-trained features more aggressively than the other settings.
- The later unfreeze gives the deeper layers time to adapt before shallow layers receive updates.
