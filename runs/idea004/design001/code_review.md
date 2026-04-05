# Code Review — idea004/design001

**Design:** Constant Decay LLRD (gamma=0.95, unfreeze_epoch=5)
**Reviewer:** Designer
**Date:** 2026-04-03
**Decision:** APPROVED (with minor style notes)

---

## Summary

The Builder's implementation in `train.py` and `config.py` is mathematically correct and structurally faithful to `design.md`. All key formulas, param group counts, freeze/unfreeze logic, and LR scheduling are implemented as specified. Two minor issues are noted but do not block approval.

---

## Verification Checklist

### LLRD Formula
- **Spec:** `lr_i = 1e-4 * 0.95^(23-i)` for blocks 0–23
- **Implementation:** `_block_lr(i) = BASE_LR_BACKBONE * (GAMMA ** (NUM_BLOCKS - 1 - block_idx))` = `1e-4 * 0.95^(23-i)`
- **Result:** PASS

### Embed LR
- **Spec:** `lr_embed = 1e-4 * 0.95^24 ≈ 2.92e-5`
- **Implementation:** `_embed_lr() = BASE_LR_BACKBONE * (GAMMA ** NUM_BLOCKS)` = `1e-4 * 0.95^24`
- **Result:** PASS

### Head LR
- **Spec:** `lr_head = 1e-4`
- **Implementation:** `LR_HEAD = 1e-4` used in both optimizer builders
- **Result:** PASS

### Progressive Unfreezing
- **Spec:** Blocks 0–11 + embeddings frozen epochs 0–4; unfrozen at start of epoch 5 by optimizer rebuild
- **Implementation:** `_build_optimizer_frozen` sets `requires_grad=False` for blocks 0–11 + patch_embed + pos_embed; at `epoch == UNFREEZE_EPOCH` (5), `_build_optimizer_full` sets `requires_grad=True` for all backbone params and rebuilds optimizer
- **Ordering:** Rebuild happens before `get_lr_scale` is applied — PASS

### Param Group Counts
- **Spec:** 13 groups (frozen phase: blocks 12–23 + head), 26 groups (full phase: embed + blocks 0–23 + head)
- **Implementation:** Both builders match exactly; print assertions confirm expected counts
- **Result:** PASS

### `initial_lr` and LR Scale Application
- **Spec:** `g["lr"] = g["initial_lr"] * scale`; `initial_lr` set at optimizer creation/rebuild
- **Implementation:** Both optimizer builders set `"initial_lr"` per group; main loop applies `g["lr"] = g["initial_lr"] * scale` every epoch
- **Result:** PASS

### LR Schedule
- **Spec:** Linear warmup 3 epochs, cosine decay; identical to baseline
- **Implementation:** `get_lr_scale(epoch, total_epochs=20, warmup_epochs=3)` with linear ramp and cosine formula
- **Result:** PASS

### weight_decay = 0.03
- **Config line 39:** `weight_decay = 0.03`
- **Usage:** `_build_optimizer_frozen(model, weight_decay=args.weight_decay)` and `_build_optimizer_full(model, weight_decay=args.weight_decay)`
- **Result:** PASS

### grad_clip = 1.0
- **Config line 41:** `grad_clip = 1.0`
- **Usage:** `nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)`
- **Result:** PASS

### epochs = 20, warmup_epochs = 3
- **Config lines 35, 41:** Both correct
- **Result:** PASS

### batch_size = 4, accum_steps = 8
- **Config:** Both pulled from `infra.py` constants (`BATCH_SIZE`, `ACCUM_STEPS`) — design notes these as "fixed"
- **Result:** PASS

### Group Index Math for LR Reporting
- **Frozen phase:** groups = [block12, block13, ..., block23, head] → block23 at index 11, head at index 12. Code uses `param_groups[11]` and `param_groups[12]` — PASS
- **Full phase:** groups = [embed, block0, ..., block23, head] → block23 at index 24, head at index 25. Code uses `param_groups[24]` and `param_groups[25]` — PASS

### `pos_embed` Handling
- **Spec:** `model.backbone.vit.pos_embed` is an `nn.Parameter`; add directly to param group
- **Implementation:** `embed_params = list(vit.patch_embed.parameters()) + [vit.pos_embed]` — correct
- **Result:** PASS

---

## Issues Found

### Issue 1 — MINOR: LLRD hyperparameters hardcoded in train.py, not config.py
**Severity:** Minor / Non-blocking

The design spec and review criteria state that experiment-specific values should be in `config.py`. The following constants are defined at module level in `train.py` (lines 51–55) rather than as config fields:

```python
GAMMA            = 0.95
BASE_LR_BACKBONE = 1e-4
LR_HEAD          = 1e-4
NUM_BLOCKS       = 24
UNFREEZE_EPOCH   = 5
```

These values are used consistently and correctly throughout `train.py`. Moving them to `config.py` would improve maintainability and allow sweeping these hyperparameters without editing the training script.

**Impact on correctness:** None. Values match design spec exactly.

### Issue 2 — MINOR: Stale `lr_backbone = 1e-5` in config.py
**Severity:** Minor / Non-blocking

`config.py` line 37 retains `lr_backbone = 1e-5`, which is the baseline value. This field is never read by `train.py` (which uses its own `BASE_LR_BACKBONE = 1e-4`). This stale attribute is dead code but creates a misleading impression that the backbone LR is 1e-5.

**Impact on correctness:** None. The field is unused.

---

## Decision

**APPROVED**

All mathematical formulas, param group structure, freeze/unfreeze logic, LR schedule, and hyperparameter values are correctly implemented per `design.md`. The two noted issues are style/maintainability concerns that do not affect experimental correctness or reproducibility. The implementation is ready to run.
