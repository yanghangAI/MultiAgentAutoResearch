# Design 001: Homoscedastic Uncertainty Loss Weighting

**Idea:** idea003 — Curriculum-Based Loss Weighting  
**Design:** Homoscedastic Uncertainty Loss Weighting  
**Status:** Not Implemented

---

## Problem

The baseline uses fixed loss weights (`lambda_depth=0.1`, `lambda_uv=0.2`) for the three task heads (pose, depth, UV). These weights were chosen heuristically and may not optimally balance gradient magnitudes across the three tasks. In particular, depth prediction is a harder task early in training, and a fixed weight can cause noisy depth gradients to destabilize relative pose learning.

---

## Proposed Solution

Apply the **Kendall et al. (2018)** homoscedastic (task) uncertainty formulation. Each task is given a learnable log-variance parameter `s = log(σ²)`. The combined loss becomes:

```
L_total = exp(-s_pose)*L_pose + s_pose
        + exp(-s_depth)*L_depth + s_depth
        + exp(-s_uv)*L_uv + s_uv
```

where:
- `L_pose`, `L_depth`, `L_uv` are the raw (unweighted) task losses (smooth_l1, beta=0.05 as in baseline)
- `s_pose`, `s_depth`, `s_uv` are **scalar** `nn.Parameter` tensors (log-variance; learned jointly with the model)
- `exp(-s)` acts as the adaptive weight; the `+s` regularisation term prevents degenerate collapse (s → ∞ sets weight to 0)

This is mathematically equivalent to the Gaussian likelihood weighting:
```
L = (1 / (2*σ²)) * L_task + log(σ)
```
rearranged using `s = log(σ²)`.

---

## Exact Implementation

### 1. Learnable Parameters

Add three scalar `nn.Parameter` objects **directly on the `SapiensPose3D` model** (not inside the head):

```python
# Inside SapiensPose3D.__init__:
self.log_var_pose  = nn.Parameter(torch.zeros(1))   # init = 0.0 → σ²=1, weight=1.0
self.log_var_depth = nn.Parameter(torch.zeros(1))   # init = 0.0 → σ²=1, weight=1.0
self.log_var_uv    = nn.Parameter(torch.zeros(1))   # init = 0.0 → σ²=1, weight=1.0
```

**Initialization rationale:** Starting at 0.0 means each task begins with effective weight 1.0 (i.e., `exp(-0)=1`). The baseline uses `lambda_depth=0.1` and `lambda_uv=0.2`; however, starting at 0 lets the model discover the right balance rather than inheriting a potentially suboptimal prior.

### 2. Loss Computation in `train_one_epoch`

Replace the baseline loss line:
```python
# BASELINE (remove):
loss = (l_pose + args.lambda_depth * l_dep + args.lambda_uv * l_uv) / args.accum_steps
```

With:
```python
# DESIGN001:
s_pose  = model.log_var_pose
s_depth = model.log_var_depth
s_uv    = model.log_var_uv

loss = (
    torch.exp(-s_pose)  * l_pose  + s_pose  +
    torch.exp(-s_depth) * l_dep   + s_depth +
    torch.exp(-s_uv)    * l_uv    + s_uv
) / args.accum_steps
```

No `lambda_depth` or `lambda_uv` config args are needed; remove them from `get_config()` or leave them unused.

### 3. Optimizer Group Assignment

The three `log_var_*` parameters must be included in the optimizer and trained at `lr_head` rate (same as the prediction head). Add a **third parameter group**:

```python
optimizer = torch.optim.AdamW(
    [
        {"params": model.backbone.parameters(),  "lr": args.lr_backbone},
        {"params": model.head.parameters(),      "lr": args.lr_head},
        {"params": [model.log_var_pose,
                    model.log_var_depth,
                    model.log_var_uv],           "lr": args.lr_head},
    ],
    weight_decay=args.weight_decay,
)
```

Also update the LR schedule loop to cover all three groups:
```python
for g in optimizer.param_groups:
    g["lr"] = g["initial_lr"] * scale
```
(this loop already iterates over all groups, so no structural change is needed — just ensure `initial_lr` is set for group index 2 as well).

### 4. Logging

Log the learned weights for inspection each epoch:
```python
w_pose  = torch.exp(-model.log_var_pose).item()
w_depth = torch.exp(-model.log_var_depth).item()
w_uv    = torch.exp(-model.log_var_uv).item()
print(f"  → learned weights: pose={w_pose:.3f}  depth={w_depth:.3f}  uv={w_uv:.3f}")
```

Add `"w_pose"`, `"w_depth"`, `"w_uv"` fields to the epoch metrics dict for CSV logging.

---

## Hyperparameters (unchanged from baseline unless noted)

| Parameter | Value | Note |
|---|---|---|
| Optimizer | AdamW | unchanged |
| lr_backbone | 1e-5 | unchanged |
| lr_head | 1e-4 | unchanged |
| lr (log_var params) | 1e-4 | same as lr_head |
| weight_decay | 0.03 | unchanged |
| epochs | 20 | unchanged |
| BATCH_SIZE | 4 | fixed in infra.py, do not change |
| ACCUM_STEPS | 8 | fixed in infra.py, do not change |
| warmup_epochs | 3 | unchanged |
| log_var_pose init | 0.0 | → effective weight 1.0 |
| log_var_depth init | 0.0 | → effective weight 1.0 |
| log_var_uv init | 0.0 | → effective weight 1.0 |
| lambda_depth | N/A | replaced by learned s_depth |
| lambda_uv | N/A | replaced by learned s_uv |

---

## Memory Budget

- Three additional scalar `nn.Parameter`s = negligible VRAM impact (~12 bytes total).
- No architectural change to backbone or head; model size is identical to baseline.
- Well within the 11GB 1080Ti budget.

---

## Expected Behaviour

- Early epochs: all three effective weights start at 1.0 and the model self-tunes the balance.
- Expected outcome: `log_var_depth` and `log_var_uv` should increase (weight decreases) if depth/UV losses are noisy; alternatively they may stay near 0 if the tasks are well-calibrated.
- The regularisation term `+s` prevents any single weight from collapsing to zero.

---

## Reference

Kendall, A., Gal, Y., & Cipolla, R. (2018). *Multi-Task Learning Using Uncertainty to Weigh Losses for Scene Geometry and Semantics.* CVPR 2018.
