# Architect Review — idea003 / design001

**Design:** Homoscedastic Uncertainty Loss Weighting (Kendall et al., 2018)  
**Verdict:** APPROVED

---

## Summary

The design proposes replacing fixed loss weights (`lambda_depth`, `lambda_uv`) with three learnable scalar log-variance parameters (`s_pose`, `s_depth`, `s_uv`) following the Kendall et al. (2018) multi-task uncertainty weighting formulation.

---

## Mathematical Correctness

The formula `exp(-s)*L + s` is the correct reduced form of the Kendall uncertainty loss:
```
L = (1/(2σ²)) * L_task + log(σ)  →  exp(-s)*L/2 + s/2
```
Dropping the `1/2` factor throughout is a constant scale that does not affect optimization or relative task balancing. The regularization term `+s` correctly prevents degenerate collapse (s → ∞ would drive effective weight to 0). This is mathematically sound.

---

## Implementation Review

**Learnable parameters**: Adding three scalar `nn.Parameter`s directly on `SapiensPose3D` (not inside the head) is appropriate. No DDP wrapping is used in the baseline, so `model.log_var_pose` is directly accessible without `model.module` indirection.

**Optimizer**: The third parameter group at `lr_head` rate is correctly structured. The existing `initial_lr` loop (`for g in optimizer.param_groups: g["initial_lr"] = g["lr"]`) already iterates over all groups, so the new group 2 is automatically covered with no structural change required — as the design correctly notes.

**Loss computation**: The replacement of the baseline loss line is correct and complete. Dividing by `args.accum_steps` is preserved.

**Logging**: Adding `w_pose`, `w_depth`, `w_uv` to the epoch metrics dict is a useful addition that will help diagnose whether the model converges on sensible weights.

---

## Risks and Notes

1. **Initial weight imbalance**: All log_vars initialize at 0.0, giving effective weight 1.0 to all tasks. The baseline uses `lambda_depth=0.1` and `lambda_uv=0.2`. This means depth and UV losses will be up to 10x more heavily weighted in early iterations than the baseline. In a 20-epoch proxy run this could cause some instability in the first few epochs before the weights self-correct. The regularization term prevents collapse and the model should adapt; this is an acceptable and intentional design risk.

2. **Unused args**: The design correctly notes that `lambda_depth` and `lambda_uv` args can be left as unused rather than removed. The Builder should leave them in `get_config()` as unused to minimize risk of breaking other infrastructure.

3. **Checkpoint resume**: If `load_checkpoint` is called with a checkpoint from a 2-group optimizer (e.g., baseline), the optimizer state will not include the third group and may warn or fail. For a fresh 20-epoch proxy run with no resume this is not an issue.

4. **Print statement cosmetic**: `lr_hd = optimizer.param_groups[1]["lr"]` references only 2 groups — the log_var group LR won't be printed separately. This is cosmetic and does not affect correctness.

---

## Memory Budget

Three scalar parameters add ~12 bytes of VRAM. No architectural changes to backbone or head. Well within the 11GB 1080Ti budget.

---

## Conclusion

The design is mathematically correct, implementation-complete, and budget-safe. The Kendall uncertainty formulation is a principled alternative to fixed loss weighting and directly addresses the stated problem (noisy depth gradients destabilizing relative pose learning). All critical implementation details (parameter placement, optimizer groups, accum_steps division, initial_lr loop coverage) are correctly handled.

**APPROVED**
