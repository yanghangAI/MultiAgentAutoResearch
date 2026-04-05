# Code Review — idea004/design003

**Design:** Constant Decay LLRD (gamma=0.85, unfreeze_epoch=5)
**Reviewer:** Designer
**Date:** 2026-04-03
**Decision:** APPROVED

---

## Summary

The Builder's implementation in `train.py` and `config.py` matches `design.md` correctly. The LLRD schedule, progressive unfreezing, param group construction, and LR scaling behavior all align with the written design. Experiment-specific hyperparameters are exposed in `config.py`, and the test run completed successfully with the required output files.

## Verification Checklist

### LLRD Formula
- Spec: `lr_i = 1e-4 * 0.85^(23-i)` for blocks 0-23
- Implementation: `_block_lr(block_idx, base_lr, gamma)` returns `base_lr * gamma ** (23 - block_idx)`
- Result: PASS

### Embedding LR
- Spec: `lr_embed = 1e-4 * 0.85^24`
- Implementation: `_embed_lr(base_lr, gamma)` returns `base_lr * gamma ** 24`
- Result: PASS

### Head LR
- Spec: `lr_head = 1e-4`
- Implementation: `args.lr_head` from `config.py`
- Result: PASS

### Progressive Unfreezing
- Spec: Freeze blocks 0-11 plus patch/pos embeddings for epochs 0-4, then rebuild optimizer at epoch 5 with all backbone params unfrozen
- Implementation: `_build_optimizer_frozen()` and `_build_optimizer_full()` match this behavior, and rebuild occurs before LR scaling at `epoch == args.unfreeze_epoch`
- Result: PASS

### Param Group Counts
- Spec: 13 groups in frozen phase, 26 groups in full phase
- Implementation: Printed counts and construction logic match the spec exactly
- Result: PASS

### Config Placement
- Spec: experiment-specific values should live in `config.py`
- Implementation: `lr_backbone`, `lr_head`, `weight_decay`, `gamma`, `unfreeze_epoch`, `warmup_epochs`, and `grad_clip` are all set in `config.py`
- Result: PASS

### Test Run
- Job: `54992317`
- Output files: `metrics.csv`, `iter_metrics.csv`
- Final printed validation body MPJPE present in stdout
- Result: PASS

## Decision

**APPROVED**

The code is faithful to the design and ready for status synchronization.
