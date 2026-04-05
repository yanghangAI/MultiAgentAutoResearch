# Design 003 — Constant Decay LLRD (gamma=0.85, unfreeze_epoch=5)

## Overview

This design applies Layer-Wise Learning Rate Decay (LLRD) to the Sapiens ViT-B backbone with the steepest decay factor in the unfreeze_epoch=5 group: gamma=0.85. Progressive unfreezing occurs at epoch 5, same as designs 001 and 002. This variant creates the strongest LR gradient (~21x ratio from deepest to shallowest block) among the early-unfreeze designs, maximally suppressing updates to shallow pre-trained features.

## Problem

Same as designs 001 and 002: prevent catastrophic forgetting of pre-trained shallow ViT representations. This design tests the extreme of the gamma search axis (gamma=0.85) with early progressive unfreezing, probing whether very strong decay ratios improve or harm adaptation.

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
- `gamma = 0.85`
- `num_blocks = 24`

Computed values:
- Block 23 (deepest):   `lr_23 = 1e-4 * 0.85^0  = 1.000e-4`
- Block 22:             `lr_22 = 1e-4 * 0.85^1  = 8.500e-5`
- Block 11 (mid):       `lr_11 = 1e-4 * 0.85^12 ≈ 1.422e-5`
- Block 0 (shallowest): `lr_0  = 1e-4 * 0.85^23 ≈ 2.096e-6`

Patch + positional embedding:
```
lr_embed = 1e-4 * 0.85^24 ≈ 1.781e-6
```

Head learning rate: `lr_head = 1e-4` (unchanged).

## Progressive Unfreezing

- **Freeze strategy:** At epoch 0, blocks 0–11 (12 shallowest blocks) and the patch/pos embedding are frozen by setting `requires_grad=False` and omitting them from optimizer param groups.
- **Unfreeze epoch:** At the start of epoch 5, all backbone params are unfrozen (`requires_grad=True` restored) and the optimizer is **rebuilt from scratch** with the full 26-group LLRD assignment.
- **Optimizer rebuild:** New `torch.optim.AdamW` with all per-block groups + embedding group + head group. `weight_decay=0.03`. Apply current LR scale to all `initial_lr` values after rebuild.

## Optimizer Param Groups

### Epochs 0–4 (frozen lower half)

- Blocks 12–23: 12 groups, `lr_i = 1e-4 * 0.85^(23-i)` for i in 12..23
- Head: 1 group, `lr = 1e-4`

Total param groups: 13

### Epochs 5–19 (all unfrozen)

- Patch+pos embedding group: `lr_embed = 1e-4 * 0.85^24 ≈ 1.781e-6`
- Blocks 0–23: 24 groups, `lr_i = 1e-4 * 0.85^(23-i)`
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
| gamma | 0.85 |
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

- gamma=0.85 creates a ~56x ratio between the deepest block LR (1e-4) and the embedding LR (~1.78e-6), and ~48x ratio to the shallowest block (~2.1e-6). This is the most aggressive shallow-layer suppression in the unfreeze_epoch=5 set.
- The shallow block LRs (~2e-6) are well below the baseline backbone LR (1e-5), meaning blocks 0–5 are nearly frozen even after unfreezing — relying on gradient signal alone. This may be beneficial if shallow features are already well-suited to the task, or may impede adaptation if some shallow re-learning is needed.
- unfreeze_epoch=5 is kept constant to isolate the gamma effect.
- Comparison with designs 001 and 002 directly reveals the sensitivity to decay steepness at fixed unfreeze timing.
