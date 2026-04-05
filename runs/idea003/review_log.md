# Review Log — idea003: Curriculum-Based Loss Weighting

---

## design001 — Homoscedastic Uncertainty Loss Weighting

**Verdict:** APPROVED

**Summary:** Replaces fixed `lambda_depth`/`lambda_uv` weights with three learnable scalar log-variance parameters following Kendall et al. (2018). Formula `exp(-s)*L + s` is mathematically correct; regularization prevents weight collapse. Three scalar parameters add negligible VRAM. Optimizer group setup and `initial_lr` loop coverage are correct. Minor risks: initial effective weight of 1.0 for all tasks (vs baseline 0.1/0.2 for depth/UV) may cause early-epoch instability, but self-corrects. No DDP concerns. Unused `lambda_depth`/`lambda_uv` args should be left in `get_config()` rather than removed. Full review at `runs/idea003/design001/review.md`.

---

## design002 — Linear Warmup for Depth Loss

**Verdict:** APPROVED

**Summary:** Linearly ramps `lambda_depth` from 0.0 to 0.1 over the first 5 epochs, then holds constant at 0.1 for epochs 5–19. `lambda_uv` remains fixed at 0.2. Mathematical formula and epoch table are correct and consistent. Implementation is clean: `get_depth_weight` function is edge-case safe, `train_one_epoch` signature addition and loss line replacement are correct, `accum_steps` division is preserved, and `args.lambda_depth` removal is safe (no residual references). LR and depth weight schedules are fully orthogonal. Zero VRAM impact; no new parameters. Well within the 20-epoch 1080Ti budget. Full review at `runs/idea003/design002/review.md`.

---
