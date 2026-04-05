# Code Review — idea004/design006

**Design:** Constant Decay LLRD (gamma=0.85, unfreeze_epoch=10)
**Reviewer:** Designer
**Date:** 2026-04-03
**Decision:** APPROVED

---

## Summary

The Builder's implementation in `train.py` and `config.py` matches `design.md` as written. The steep LLRD decay, progressive unfreezing at epoch 10, param-group rebuild behavior, and config placement of experiment-specific values all match the spec. The test run completed successfully and produced the required metrics files.

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
- Spec: Freeze blocks 0-11 plus patch/pos embeddings for epochs 0-9, then rebuild optimizer at epoch 10 with all backbone params unfrozen
- Implementation: `_build_optimizer_frozen()` and `_build_optimizer_full()` match this behavior, and the rebuild occurs at `epoch == args.unfreeze_epoch`
- Result: PASS

### Param Group Counts
- Spec: 13 groups in frozen phase, 26 groups in full phase
- Implementation: Construction logic matches the spec exactly
- Result: PASS

### Config Placement
- Spec: experiment-specific values should live in `config.py`
- Implementation: `lr_backbone`, `lr_head`, `weight_decay`, `gamma`, `unfreeze_epoch`, `warmup_epochs`, and `grad_clip` are all set in `config.py`
- Result: PASS

### Test Run
- Job: `54992705`
- Output files: `metrics.csv`, `iter_metrics.csv`
- Final printed validation body MPJPE present in stdout
- Result: PASS

## Decision

**APPROVED**

The code is faithful to the design and ready for tracker synchronization.
