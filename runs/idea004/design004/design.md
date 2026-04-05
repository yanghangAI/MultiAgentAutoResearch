# Design 004 — Constant Decay LLRD (gamma=0.95, unfreeze_epoch=10)

## Overview

This design applies Layer-Wise Learning Rate Decay (LLRD) to the Sapiens ViT-B backbone with gamma=0.95 and a later progressive unfreezing at epoch 10. Compared to design001 (same gamma, unfreeze at epoch 5), the frozen shallow blocks are held frozen for twice as long, giving the head and deep backbone blocks a full 10 warm-up epochs to stabilize before shallow layers are unlocked. This tests whether later unfreezing leads to better final performance by reducing interference during the critical early adaptation phase.

## Problem

Same as previous designs: prevent catastrophic forgetting of shallow pre-trained ViT features while allowing the network to adapt to depth-aware 3D pose estimation. This design isolates the effect of unfreeze timing — doubling it from 5 to 10 epochs — while keeping gamma constant at 0.95.

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

Computed values (identical to design001):
- Block 23 (deepest):   `lr_23 = 1e-4 * 0.95^0  = 1.000e-4`
- Block 22:             `lr_22 = 1e-4 * 0.95^1  = 9.500e-5`
- Block 11 (mid):       `lr_11 = 1e-4 * 0.95^12 ≈ 5.404e-5`
- Block 0 (shallowest): `lr_0  = 1e-4 * 0.95^23 ≈ 3.073e-5`

Patch + positional embedding:
```
lr_embed = 1e-4 * 0.95^24 ≈ 2.919e-5
```

Head learning rate: `lr_head = 1e-4` (unchanged).

## Progressive Unfreezing

- **Freeze strategy:** At epoch 0, blocks 0–11 (12 shallowest blocks) and the patch/pos embedding are frozen by setting `requires_grad=False` and omitting them from optimizer param groups.
- **Unfreeze epoch:** At the start of epoch 10, all backbone params are unfrozen (`requires_grad=True` restored) and the optimizer is **rebuilt from scratch** with the full 26-group LLRD assignment.
- **Optimizer rebuild:** New `torch.optim.AdamW` with all per-block groups + embedding group + head group. `weight_decay=0.03`. Apply current LR scale (cosine phase, epoch 10) to all `initial_lr` values after rebuild.

Note: At epoch 10, the cosine decay scale is:
```
scale = get_lr_scale(10, total_epochs=20, warmup_epochs=3)
      = 0.5 * (1 + cos(π * (10-3)/(20-3)))
      = 0.5 * (1 + cos(π * 7/17))
      ≈ 0.5 * (1 + cos(1.295))
      ≈ 0.5 * (1 + 0.2675)
      ≈ 0.634
```

So the effective LR at rebuild will be `initial_lr * 0.634` for each group.

## Optimizer Param Groups

### Epochs 0–9 (frozen lower half)

- Blocks 12–23: 12 groups, `lr_i = 1e-4 * 0.95^(23-i)` for i in 12..23
- Head: 1 group, `lr = 1e-4`

Total param groups: 13

### Epochs 10–19 (all unfrozen)

- Patch+pos embedding group: `lr_embed = 1e-4 * 0.95^24 ≈ 2.919e-5`
- Blocks 0–23: 24 groups, `lr_i = 1e-4 * 0.95^(23-i)`
- Head: 1 group, `lr = 1e-4`

Total param groups: 26

## LR Schedule

Identical to baseline: linear warmup for 3 epochs, cosine decay thereafter.

```python
scale = get_lr_scale(epoch, total_epochs=20, warmup_epochs=3)
for g in optimizer.param_groups:
    g["lr"] = g["initial_lr"] * scale
```

After optimizer rebuild at epoch 10, set `initial_lr` per-group and apply current scale before the first training step of that epoch.

## Config Summary

| Parameter | Value |
|-----------|-------|
| gamma | 0.95 |
| base_lr_backbone (deepest block) | 1e-4 |
| lr_head | 1e-4 |
| unfreeze_epoch | 10 |
| frozen blocks (epochs 0–9) | 0–11 + embeddings |
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
5. At `unfreeze_epoch=10`: set `requires_grad=True` for all backbone params, rebuild optimizer, restore scaler state.
6. Optimizer rebuild must happen before `get_lr_scale` is applied at that epoch.

## Rationale

- Extending the freeze period to epoch 10 (half of the 20-epoch training) gives deep layers and the head a full warmup before the shallow layers participate. This may produce a more stable training trajectory at the cost of only 10 active epochs for shallow layer adaptation.
- gamma=0.95 is kept gentle so that, when blocks 0–11 finally unfreeze, they receive meaningful (not vanishingly small) learning rates (~3e-5), enabling real adaptation in the available 10 remaining epochs.
- Comparison with design001 (same gamma, unfreeze=5) directly isolates the unfreeze timing effect.
- The cosine schedule will have decayed to ~63% of initial LR at epoch 10, so the newly unfrozen blocks will start learning at a moderate rate — neither too aggressive nor negligible.
