# Architect Review — idea003 / design002

**Design:** Linear Warmup for Depth Loss Weight  
**Verdict:** APPROVED

---

## Summary

The design proposes a linear warmup schedule for `lambda_depth`, ramping from 0.0 at epoch 0 to 0.1 over the first 5 epochs, then holding constant at 0.1 for epochs 5–19. `lambda_uv` remains fixed at 0.2 throughout. No architectural changes are made.

---

## Mathematical Correctness

The warmup formula `start_weight + (target_weight - start_weight) * (epoch / warmup_epochs)` with `start_weight=0.0, target_weight=0.1, warmup_epochs=5` produces:

| Epoch | Weight |
|-------|--------|
| 0     | 0.000  |
| 1     | 0.020  |
| 2     | 0.040  |
| 3     | 0.060  |
| 4     | 0.080  |
| 5–19  | 0.100  |

This matches the table in the design exactly. The edge-case guard (`warmup_epochs <= 0` returns `target_weight` immediately) is correct. ✓

---

## Implementation Review

**Config changes**: Replacing `lambda_depth` with `depth_start_weight`, `depth_target_weight`, `depth_warmup_epochs` is clean. Since `args.lambda_depth` is only referenced in the loss line of `train_one_epoch`, and the design explicitly replaces that line, removal is safe with no residual dangling references.

**`get_depth_weight` function**: Signature and logic are correct. Default behavior when `warmup_epochs <= 0` returns `target_weight`, making it a no-op drop-in for constant-weight behavior.

**Epoch loop**: `current_depth_weight` is computed from the 0-indexed loop variable `epoch`, which is correct. This is passed directly to `train_one_epoch` as a float, bypassing `args`.

**`train_one_epoch` signature**: Default value `depth_weight: float = 0.1` matches baseline asymptotic value — correct fallback. The call site passes `depth_weight=current_depth_weight` explicitly, so the default is never relied upon during training.

**Loss line replacement**: `depth_weight * l_dep` correctly replaces `args.lambda_depth * l_dep`. Division by `args.accum_steps` is preserved. ✓

**LR schedule independence**: The LR cosine schedule operates on optimizer parameter groups; the depth weight schedule operates on a Python float passed to the loss function. They are fully orthogonal. LR warmup runs for 3 epochs; depth warmup runs for 5 epochs — no coupling. ✓

**Checkpoint resume**: If `start_epoch > 0`, the depth warmup uses the absolute 0-indexed epoch, so the schedule will pick up at the correct point. No issue.

---

## Risks and Notes

1. **No learnable parameters added**: The schedule is a deterministic Python function evaluated once per epoch. Zero VRAM overhead, zero optimizer state changes. ✓
2. **Epoch 0 depth weight is exactly 0.0**: This means depth loss contributes nothing to epoch 0 gradients. This is intentional and is the core hypothesis of the design. The model only receives pose and UV gradient signal in the first epoch.
3. **No interaction with design001**: Design001 uses learnable homoscedastic weights; this design uses a fixed schedule. They are distinct experimental variants and do not overlap.
4. **Logging**: Adding `depth_weight` to the epoch CSV is useful for post-hoc verification that the schedule ran as intended.

---

## Memory Budget

No new parameters, modules, or data structures. The entire change is a Python float computation per epoch plus a function call. Well within the 11GB 1080Ti budget. ✓

---

## Conclusion

The design is mathematically correct, implementation-complete, budget-safe, and clearly distinct from the baseline and design001. The linear warmup hypothesis is well-motivated and straightforward to implement. All details (signature, loss line, config, logging) are correctly specified.

**APPROVED**
