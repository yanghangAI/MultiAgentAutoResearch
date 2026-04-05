# Design 002: Linear Warmup for Depth Loss

**Idea:** idea003 — Curriculum-Based Loss Weighting  
**Design:** Linear Warmup for Depth Loss  
**Status:** Not Implemented

---

## Problem

The baseline applies a constant `lambda_depth=0.1` throughout all 20 training epochs. Early in training, the model has not yet learned meaningful body pose representations, and the depth prediction head produces noisy gradients. Applying a non-zero depth loss from epoch 0 can corrupt the early body-pose learning signal.

A simple, interpretable fix: start with zero depth weight and linearly increase it to the target weight over a warmup window, after which it remains constant. This allows the body pose branch to stabilise before depth loss is introduced.

---

## Proposed Solution

Implement a **linear warmup schedule for `lambda_depth` only**. The UV loss weight remains fixed throughout training (matching the baseline).

### Schedule Definition

```
depth_weight(epoch) =
    target_weight * (epoch / depth_warmup_epochs)    if epoch < depth_warmup_epochs
    target_weight                                     if epoch >= depth_warmup_epochs
```

Where:
- `epoch` is 0-indexed (i.e., epoch 0 is the first epoch)
- `start_weight = 0.0` (depth loss is completely off at epoch 0)
- `target_weight = 0.1` (matches the baseline's `lambda_depth`; this is the asymptotic value)
- `depth_warmup_epochs = 5` (warmup runs over epochs 0–4; full weight from epoch 5 onward)

Over 20 total epochs this means:
- Epoch 0: weight = 0.000
- Epoch 1: weight = 0.020
- Epoch 2: weight = 0.040
- Epoch 3: weight = 0.060
- Epoch 4: weight = 0.080
- Epoch 5–19: weight = 0.100 (constant at target)

The UV weight is **not** warmed up; it stays fixed at `lambda_uv = 0.2` for all epochs.

---

## Exact Implementation

### 1. Config Parameters

Add the following to `get_config()`:

```python
# Loss weight schedule
lambda_uv          = 0.2    # fixed throughout (unchanged from baseline)
depth_start_weight = 0.0    # initial depth loss weight
depth_target_weight = 0.1   # target depth loss weight (matches baseline)
depth_warmup_epochs = 5     # number of epochs to linearly ramp depth weight
```

Remove `lambda_depth` from the config (it is replaced by the schedule).

### 2. Weight Schedule Function

Add this standalone function (e.g., near `get_lr_scale`):

```python
def get_depth_weight(epoch: int, start_weight: float, target_weight: float,
                     warmup_epochs: int) -> float:
    """Linear warmup for depth loss weight. epoch is 0-indexed."""
    if warmup_epochs <= 0 or epoch >= warmup_epochs:
        return target_weight
    return start_weight + (target_weight - start_weight) * (epoch / warmup_epochs)
```

### 3. Per-Epoch Weight Computation in `main()`

Inside the epoch loop, compute the current depth weight **before** calling `train_one_epoch`:

```python
for epoch in range(start_epoch, args.epochs):
    # LR schedule (unchanged)
    scale = get_lr_scale(epoch, args.epochs, args.warmup_epochs)
    for g in optimizer.param_groups:
        g["lr"] = g["initial_lr"] * scale

    # Depth loss weight schedule
    current_depth_weight = get_depth_weight(
        epoch,
        args.depth_start_weight,
        args.depth_target_weight,
        args.depth_warmup_epochs,
    )

    lr_bb = optimizer.param_groups[0]["lr"]
    lr_hd = optimizer.param_groups[1]["lr"]
    print(f"Epoch {epoch+1}/{args.epochs}  lr_backbone={lr_bb:.2e}  lr_head={lr_hd:.2e}"
          f"  depth_w={current_depth_weight:.4f}")

    train_m = train_one_epoch(
        model, train_loader, optimizer, scaler, device, epoch + 1, args,
        iter_logger=iter_logger,
        depth_weight=current_depth_weight,   # <-- pass as argument
    )
```

### 4. `train_one_epoch` Signature and Loss

Add `depth_weight: float` as a parameter to `train_one_epoch`:

```python
def train_one_epoch(model, loader, optimizer, scaler, device, epoch, args,
                    iter_logger=None, depth_weight: float = 0.1) -> dict:
```

Replace the baseline loss line:
```python
# BASELINE (remove):
loss = (l_pose + args.lambda_depth * l_dep + args.lambda_uv * l_uv) / args.accum_steps
```

With:
```python
# DESIGN002:
loss = (l_pose + depth_weight * l_dep + args.lambda_uv * l_uv) / args.accum_steps
```

`args.lambda_uv` remains 0.2 and is read from config as normal.

### 5. Interaction with LR Cosine Schedule

The LR cosine schedule (`get_lr_scale`) operates on the **optimizer parameter groups** — it is completely independent of the depth weight schedule. Both schedules run in parallel over the same epoch loop with no coupling:

- LR warmup: epochs 0–2 (3 epochs, `warmup_epochs=3` in args)
- Depth weight warmup: epochs 0–4 (5 epochs, `depth_warmup_epochs=5` in args)

There is no interaction or coupling between the two schedules. The LR schedule governs how fast parameters are updated; the depth weight governs the gradient signal from the depth head. They are orthogonal.

### 6. Optimizer (unchanged from baseline)

```python
optimizer = torch.optim.AdamW(
    [{"params": model.backbone.parameters(), "lr": args.lr_backbone},
     {"params": model.head.parameters(),     "lr": args.lr_head}],
    weight_decay=args.weight_decay,
)
```

No new parameter groups are needed (there are no learnable weight parameters).

### 7. Logging

Log `current_depth_weight` in the epoch CSV:
```python
logger.log({
    "epoch": epoch + 1,
    "lr_backbone": lr_bb,
    "lr_head": lr_hd,
    "depth_weight": current_depth_weight,
    **train_m,
    **(val_m or {}),
    "epoch_time": epoch_time,
})
```

---

## Hyperparameters

| Parameter | Value | Note |
|---|---|---|
| Optimizer | AdamW | unchanged |
| lr_backbone | 1e-5 | unchanged |
| lr_head | 1e-4 | unchanged |
| weight_decay | 0.03 | unchanged |
| epochs | 20 | unchanged |
| BATCH_SIZE | 4 | fixed in infra.py, do not change |
| ACCUM_STEPS | 8 | fixed in infra.py, do not change |
| warmup_epochs (LR) | 3 | unchanged |
| lambda_uv | 0.2 | fixed, unchanged from baseline |
| depth_start_weight | 0.0 | depth off at epoch 0 |
| depth_target_weight | 0.1 | matches baseline asymptotic value |
| depth_warmup_epochs | 5 | ramp over first 5 epochs |

---

## Memory Budget

- No new parameters or modules added.
- The schedule is computed with a single Python float computation per epoch.
- Zero VRAM impact; identical architecture to baseline.
- Well within the 11GB 1080Ti budget.

---

## Expected Behaviour

- Epochs 0–4: pose branch trains with reduced or no depth gradient interference, stabilising body joint predictions early.
- Epochs 5–19: depth loss fully active at `lambda_depth=0.1`, matching the baseline's steady-state weighting.
- If the warmup helps, we expect lower `train_mpjpe_body` in early epochs and similar or better final `val_mpjpe_weighted` compared to the constant-weight baseline.
