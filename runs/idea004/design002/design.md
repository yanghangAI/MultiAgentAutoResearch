# Design 002 — Constant Decay LLRD (gamma=0.90, unfreeze_epoch=5)

## Overview

This design applies Layer-Wise Learning Rate Decay (LLRD) to the Sapiens ViT-B backbone with a steeper decay factor gamma=0.90 and progressive unfreezing at epoch 5. Compared to design001 (gamma=0.95), this variant creates a stronger gradient between deep and shallow layer learning rates (~8x ratio vs ~3x), enforcing stronger preservation of shallow pre-trained features.

## Problem

Same as design001: prevent catastrophic forgetting of pre-trained shallow ViT representations when fine-tuning on depth-aware 3D pose estimation. This design tests whether a steeper LLRD decay (gamma=0.90) better protects those representations compared to the gentle gamma=0.95.

## Architecture

- **Backbone:** Sapiens ViT-B (`sapiens_0.3b`), 24 transformer blocks (indices 0–23)
- **Head:** Transformer decoder with 4 layers (unchanged from baseline)
- **No new parameters introduced**

## LLRD Formula

Block index `i` runs from 0 (shallowest) to 23 (deepest).

```
lr_i = base_lr_backbone * gamma^(num_blocks - 1 - i)
```

Where:
- `base_lr_backbone = 1e-4` (applied to the deepest block, block 23)
- `gamma = 0.90`
- `num_blocks = 24`

Computed values:
- Block 23 (deepest):   `lr_23 = 1e-4 * 0.90^0  = 1.000e-4`
- Block 22:             `lr_22 = 1e-4 * 0.90^1  = 9.000e-5`
- Block 11 (mid):       `lr_11 = 1e-4 * 0.90^12 ≈ 2.824e-5`
- Block 0 (shallowest): `lr_0  = 1e-4 * 0.90^23 ≈ 8.904e-6`

Patch + positional embedding:
```
lr_embed = 1e-4 * 0.90^24 ≈ 8.014e-6
```

Head learning rate: `lr_head = 1e-4` (unchanged).

## Progressive Unfreezing

- **Freeze strategy:** At epoch 0, blocks 0–11 (12 shallowest blocks) and the patch/pos embedding are frozen by setting `requires_grad=False` and omitting them from optimizer param groups.
- **Unfreeze epoch:** At the start of epoch 5, all backbone params are unfrozen (`requires_grad=True` restored) and the optimizer is **rebuilt from scratch** with the full 26-group LLRD assignment.
- **Optimizer rebuild:** New `torch.optim.AdamW` with all per-block groups + embedding group + head group. `weight_decay=0.03`. Apply current LR scale immediately to all `initial_lr` values after rebuild.

## Optimizer Param Groups

### Epochs 0–4 (frozen lower half)

- Blocks 12–23: 12 groups, `lr_i = 1e-4 * 0.90^(23-i)` for i in 12..23
- Head: 1 group, `lr = 1e-4`

Total param groups: 13

### Epochs 5–19 (all unfrozen)

- Patch+pos embedding group: `lr_embed = 1e-4 * 0.90^24 ≈ 8.014e-6`
- Blocks 0–23: 24 groups, `lr_i = 1e-4 * 0.90^(23-i)`
- Head: 1 group, `lr = 1e-4`

Total param groups: 26

## LR Schedule

Identical to baseline: linear warmup for 3 epochs, cosine decay thereafter.

```python
scale = get_lr_scale(epoch, total_epochs=20, warmup_epochs=3)
for g in optimizer.param_groups:
    g["lr"] = g["initial_lr"] * scale
```

After optimizer rebuild at epoch 5, set `initial_lr` per-group and apply current scale before the first training step of that epoch.

## Config Summary

| Parameter | Value |
|-----------|-------|
| gamma | 0.90 |
| base_lr_backbone (deepest block) | 1e-4 |
| lr_head | 1e-4 |
| unfreeze_epoch | 5 |
| frozen blocks (epochs 0–4) | 0–11 + embeddings |
| weight_decay | 0.03 |
| epochs | 20 |
| warmup_epochs | 3 |
| BATCH_SIZE | 4 (fixed) |
| ACCUM_STEPS | 8 (fixed) |
| grad_clip | 1.0 |

## Implementation Notes

1. Access ViT blocks via `model.backbone.vit.layers` (ModuleList of length 24).
2. Patch embedding params: `model.backbone.vit.patch_embed.parameters()`
3. Positional embedding: `model.backbone.vit.pos_embed` (nn.Parameter, wrap in a param group).
4. Freeze: set `requires_grad=False` for blocks 0–11 + embeddings; omit from optimizer param groups.
5. At `unfreeze_epoch=5`: set `requires_grad=True` for all backbone params, rebuild optimizer, restore scaler state.
6. Optimizer rebuild must happen before `get_lr_scale` is applied at that epoch.

## Rationale

- gamma=0.90 creates an ~11x ratio between the deepest block LR (1e-4) and the shallowest block LR (~9e-6), compared to the ~3x ratio in design001.
- This stronger decay is hypothesized to better protect the lower-level pre-trained features (edges, body part structure) while still allowing deeper blocks to adapt aggressively.
- unfreeze_epoch=5 is kept the same as design001 to isolate the effect of gamma variation from unfreeze schedule variation.
- The shallowest block LR (~9e-6) is comparable to the baseline's single backbone LR (1e-5), so the shallow blocks are not completely suppressed — just more conservatively updated than the deeper blocks.
