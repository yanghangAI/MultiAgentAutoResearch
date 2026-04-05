---
Design_ID: design003
Status: APPROVED
---

## Review

**LLRD Formula:** Mathematically correct and consistent with designs 001 and 002. Block 23 (deepest) lr = 1e-4 * 0.85^0 = 1e-4; block 0 (shallowest) lr = 1e-4 * 0.85^23 ≈ 2.096e-6; embed lr ≈ 1.781e-6. These match the tabulated values in the design body.

**Minor inconsistency:** The overview claims "~21x ratio from deepest to shallowest block," but the actual ratio is 1e-4 / 2.096e-6 ≈ **47.7x** (~48x). The rationale section correctly states ~48x. This is a prose error only — the formulas and computed values in the body are correct and self-consistent. Implementers should use the formula and tabulated values, not the overview description.

**Memory budget:** No new parameters introduced. Same architecture as baseline; fits 11GB GPU easily.

**Progressive unfreezing:** Identical strategy to designs 001/002 — freeze blocks 0–11 + embeddings for epochs 0–4, unfreeze all at epoch 5 with full optimizer rebuild. Optimizer rebuild procedure (per-group `initial_lr` assignment, scaler state restoration, scale application before first step) is well-specified.

**LR schedule:** Linear warmup 3 epochs, cosine decay thereafter, applied via scale to `initial_lr` — consistent with other designs.

**Risk:** With shallow block LRs ~2e-6 (50x below head LR), blocks 0–5 are nearly frozen post-unfreeze. This is the intended extreme of the decay axis. Gradient signal alone drives shallow adaptation — acceptable given the design's explicit goal of probing this extreme. base_lr_backbone = 1e-4 (10x baseline) carries mild instability risk during epochs 3–4, same as designs 001/002.

**Constants:** BATCH_SIZE=4, ACCUM_STEPS=8 unchanged. 20 epochs, warmup_epochs=3, weight_decay=0.03, grad_clip=1.0 all correct.

**Verdict:** APPROVED. The design is a valid and distinct variation (gamma=0.85 vs 0.95 and 0.90 in designs 001/002), correctly specified, and implementable within budget.
