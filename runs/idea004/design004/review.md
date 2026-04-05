Design_ID: design004
Status: APPROVED

## Review

**Mathematical Correctness:**
- LLRD formula is correct: `lr_i = 1e-4 * 0.95^(23-i)`. Block 23: 1e-4, Block 0: ~3.073e-5, embed: ~2.919e-5. All values verified.
- Cosine scale at epoch 10: `0.5*(1+cos(π*7/17)) ≈ 0.634`. Correctly computed and documented.
- Effective LR at unfreeze for shallow blocks: ~3e-5 * 0.634 ≈ 1.9e-5 — low but non-negligible, appropriate for gentle late adaptation.

**Implementation Soundness:**
- Optimizer rebuild at epoch 10 with per-group `initial_lr` assignment before scale application is clearly specified.
- Scaler state restoration is mentioned. Param group counts (13 before, 26 after) are consistent with frozen/unfrozen sets.
- `model.backbone.vit.layers` access confirmed valid from prior designs.

**Budget:**
- No new parameters introduced. Memory well within 11GB.
- 20 epochs total, 10 active epochs for deep blocks + head only, then 10 epochs for all blocks. Tight but within proxy budget.

**Risks:**
- Shallow blocks (0–11) only have 10 remaining epochs post-unfreeze, and the cosine LR continues decaying through this window, so effective adaptation time is compressed. This is the design intent and acceptable given design001 (5-epoch unfreeze) provides the comparison point.
- base_lr_backbone=1e-4 (same as prior designs); mild instability risk during warmup/post-warmup remains, consistent with accepted tradeoff in designs 001–003.
- gamma=0.95 keeps shallow-block LRs meaningful (~1.9e-5 at unfreeze, decaying further), distinguishing this from the more aggressive decay in design003.

**Verdict:** Design isolates unfreeze timing (epoch 10 vs epoch 5) while holding gamma=0.95 constant — a valid, distinct comparison against design001. All constants fixed per `infra.py`. APPROVED.
