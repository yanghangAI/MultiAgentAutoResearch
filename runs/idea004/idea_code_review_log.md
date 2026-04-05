# idea004 — Code Review Log

---

## Entry 1

**Design_ID:** design001
**Reviewer:** Designer
**Date:** 2026-04-03
**Decision:** APPROVED

### Summary

Reviewed `train.py` and `config.py` for idea004/design001 (Constant Decay LLRD, gamma=0.95, unfreeze_epoch=5) against `design.md`.

### Detailed Feedback

**All checks passed:**
- LLRD formula `lr_i = 1e-4 * 0.95^(23-i)` correctly implemented in `_block_lr()`
- Embed LR `1e-4 * 0.95^24` correctly implemented in `_embed_lr()`
- Head LR `1e-4` correct
- Progressive unfreezing: blocks 0–11 + embeddings frozen epochs 0–4; optimizer rebuilt at epoch 5 before LR scale is applied
- Param group counts: 13 (frozen phase) and 26 (full phase) — both correct
- `initial_lr` set per group at optimizer creation; `g["lr"] = g["initial_lr"] * scale` applied each epoch
- LR schedule: linear warmup 3 epochs + cosine decay — correct
- weight_decay=0.03, grad_clip=1.0, epochs=20, warmup_epochs=3, batch_size=4 (from infra), accum_steps=8 (from infra) — all match spec
- Group index math for LR reporting correct in both phases
- `pos_embed` (nn.Parameter) added directly to embed param group — correct

**Issues (non-blocking):**
1. LLRD hyperparameters (`GAMMA`, `BASE_LR_BACKBONE`, `LR_HEAD`, `NUM_BLOCKS`, `UNFREEZE_EPOCH`) are module-level constants in `train.py` rather than fields in `config.py`. Values are correct but should ideally be centralized in config for sweepability.
2. `config.py` retains stale `lr_backbone = 1e-5` (baseline value) which is never read by `train.py`. Dead code — no correctness impact.

**Conclusion:** Implementation is mathematically and structurally correct per design spec. Ready to run.
