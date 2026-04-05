# Review: Design 001 — Constant Decay LLRD (gamma=0.95, unfreeze_epoch=5)

**Design_ID:** design001
**Status:** APPROVED

## Summary

The design proposes Layer-Wise Learning Rate Decay (LLRD) with progressive unfreezing on the Sapiens ViT-B backbone. It is well-motivated, mathematically explicit, and implementable within the 20-epoch proxy budget on a single 1080ti.

## Verification

- **`model.backbone.vit.layers`**: Confirmed correct. `VisionTransformer` from `mmpretrain` stores transformer blocks in `self.layers`.
- **No new parameters**: Memory budget unaffected. Easily fits within 11GB.
- **20-epoch budget**: Fully respected; optimizer rebuild at epoch 5 is a one-time cost.
- **Fixed constants respected**: `BATCH_SIZE`, `ACCUM_STEPS`, and other `infra.py` constants are unchanged.

## Strengths

1. **Well-motivated**: LLRD is an established technique for preventing catastrophic forgetting in fine-tuned ViTs. Appropriate for adapting a pretrained RGB Sapiens backbone to depth-aware 3D pose estimation.
2. **Mathematical correctness**: LLRD formula `lr_i = 1e-4 * 0.95^(23-i)` and embedding decay `0.95^24` are self-consistent. Example values in the design are verified.
3. **Optimizer rebuild design**: Rebuilding `AdamW` at `unfreeze_epoch` with correct `initial_lr` per group is the right pattern. Scaler state is independent and does not need special handling.
4. **LR schedule ordering**: "rebuild before `get_lr_scale` is applied" is correctly specified.

## Risks and Notes

1. **Aggressive backbone LR**: `base_lr_backbone=1e-4` (deepest block) is 10x higher than the baseline `1e-5`. The average LLRD backbone LR across 24 blocks is ~6.5e-5 — roughly 6.5x above baseline. This is intentional but should be monitored for instability in early epochs 3–4 (post-warmup, pre-unfreeze).
2. **No warmup for unfrozen shallow blocks**: Blocks 0–11 are activated at epoch 5 without a dedicated warmup ramp. Their LRs (~3e-5 at the shallowest) are low enough to mitigate this, but the cosine decay will have already reduced the scale factor, meaning they effectively start at a reduced LR relative to `initial_lr`. This is acceptable.
3. **Only 15 active training epochs for shallow blocks**: Blocks 0–11 are trained for epochs 5–19 only. This may limit adaptation of early backbone features, but is the intended tradeoff of progressive unfreezing.

## Conclusion

Design is sound, implementable, and a genuine departure from the baseline. No mathematical errors or budget violations found.

**APPROVED**
