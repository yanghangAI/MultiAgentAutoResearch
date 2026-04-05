# Design 001 — Constant Decay LLRD (gamma=0.95, unfreeze_epoch=5)

## Overview

This design introduces Layer-Wise Learning Rate Decay (LLRD) to the Sapiens ViT-B backbone. Instead of a single flat learning rate for the entire backbone (as in the baseline), each transformer block receives a distinct learning rate that decays exponentially from the deepest (highest-index) block to the shallowest (index 0). The head retains its own independent learning rate. Progressive unfreezing freezes the lower (shallower) backbone blocks at the start of training and unfreezes them at a specified epoch.

This is **not** a reimplementation of the baseline. The baseline uses a single backbone param group with lr=1e-5 and no freezing. This design applies structured per-block LR assignment with progressive unfreezing.

## Problem

The Sapiens ViT-B backbone is pre-trained on RGB human body data. Fine-tuning all layers at the same rate risks overwriting well-learned shallow representations (edges, textures, body parts) while the model adapts to the new depth-aware 3D pose estimation task. LLRD assigns lower learning rates to shallower (earlier, more general) blocks to prevent catastrophic forgetting.

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
- `gamma = 0.95`
- `num_blocks = 24`

This means:
- Block 23 (deepest):  `lr_23 = 1e-4 * 0.95^0 = 1.000e-4`
- Block 22:            `lr_22 = 1e-4 * 0.95^1 = 9.500e-5`
- Block 11 (mid):      `lr_11 = 1e-4 * 0.95^12 ≈ 5.40e-5`
- Block 0 (shallowest): `lr_0  = 1e-4 * 0.95^23 ≈ 3.07e-5`

The patch embedding and positional embedding also receive a decayed rate:
```
lr_embed = base_lr_backbone * gamma^(num_blocks)
         = 1e-4 * 0.95^24 ≈ 2.92e-5
```

The head learning rate is unchanged: `lr_head = 1e-4`.

## Progressive Unfreezing

- **Freeze strategy:** At epoch 0, blocks 0–11 (the 12 shallowest blocks) and the patch/pos embedding are frozen. Frozen means they are **excluded from the optimizer param groups** (not added at all), so they receive zero gradient and zero update.
- **Unfreeze epoch:** At the start of epoch 5 (i.e., before the epoch 5 forward pass), blocks 0–11 and embeddings are unfrozen by **rebuilding all optimizer param groups** from scratch with the full LLRD assignment.
- **Optimizer rebuild:** When unfreezing, construct a new `torch.optim.AdamW` with the complete list of per-block param groups (blocks 0–23 + embeddings + head), using the same `weight_decay=0.03`. The LR schedule scale at that epoch is reapplied to all groups via `initial_lr`.

## Optimizer Param Groups

### Epochs 0–4 (frozen lower half)

One param group per active component:
- Blocks 12–23: 12 groups, `lr_i = 1e-4 * gamma^(23-i)` for i in 12..23
- Head: 1 group, `lr = 1e-4`

Total param groups: 13

### Epochs 5–19 (all unfrozen)

One param group per block + embedding + head:
- Patch+pos embedding group: `lr_embed = 1e-4 * 0.95^24 ≈ 2.92e-5`
- Blocks 0–23: 24 groups, `lr_i = 1e-4 * 0.95^(23-i)`
- Head: 1 group, `lr = 1e-4`

Total param groups: 26

## LR Schedule

Identical to baseline: linear warmup for 3 epochs, then cosine decay.

```python
scale = get_lr_scale(epoch, total_epochs=20, warmup_epochs=3)
for g in optimizer.param_groups:
    g["lr"] = g["initial_lr"] * scale
```

The `initial_lr` for each group is set once when the optimizer is created (or rebuilt at unfreeze). After rebuild at epoch 5, `initial_lr` values are set to the per-block LLRD values above, and the scale at that epoch is applied immediately before the first step.

## Config Summary

| Parameter | Value |
|-----------|-------|
| gamma | 0.95 |
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

1. Access ViT blocks via `model.backbone.vit.layers` (a `ModuleList` of length 24).
2. Patch embedding params: `model.backbone.vit.patch_embed.parameters()`
3. Positional embedding: `model.backbone.vit.pos_embed` (a `nn.Parameter`, wrap in a param group directly).
4. When freezing, set `param.requires_grad = False` for frozen params (or simply omit them from optimizer groups). Preferred: omit from optimizer groups entirely and set `requires_grad=False`.
5. At unfreeze_epoch, set `requires_grad=True` for all backbone params, rebuild optimizer, restore scaler state.
6. The optimizer rebuild must happen **before** `get_lr_scale` is applied at that epoch.

## Rationale

- gamma=0.95 provides gentle decay (~3x ratio from shallowest to deepest block), preserving pre-trained shallow features without overly suppressing learning in deeper blocks.
- unfreeze_epoch=5 gives the head and deep blocks 5 warm-up epochs to adapt before shallow layers are unlocked, reducing risk of destabilization.
- base_lr_backbone=1e-4 at the deepest block (rather than 1e-5) is intentional: LLRD redistributes the effective average backbone LR, so the deepest block gets the same order of magnitude as the head.
