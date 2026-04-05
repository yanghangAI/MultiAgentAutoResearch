# Code Review Log: idea002

---

## Entry 1

**Design ID:** design001
**Design Name:** Baseline Dense (Control)
**Reviewer:** Experiment Designer
**Review Date:** 2026-04-02
**Verdict:** APPROVED

### Summary

The `train.py` implementation precisely matches all specifications in `design.md`:

- `_build_hop_distance_matrix` and `HOP_DIST` are defined at module level with exact BFS logic, `fill_value=num_joints`, `dtype=torch.long`, and `SMPLX_SKELETON` edges — matching the spec verbatim.
- `Pose3DHead` accepts `attention_method: str = "dense"`, passes `tgt_mask=None` to `self.decoder(queries, memory, tgt_mask=None)`, and has all correct head parameters (`num_joints=70`, `hidden_dim=256`, `num_heads=8`, `num_layers=4`, `dropout=0.1`).
- All training hyperparameters match the spec: `epochs=20`, `lr_backbone=1e-5`, `lr_head=1e-4`, `weight_decay=0.03`, `warmup_epochs=3`, `grad_clip=1.0`, `lambda_depth=0.1`, `lambda_uv=0.2`, `amp=False`.
- Optimizer and LR schedule match the design's specified AdamW two-group construction and cosine+warmup schedule.
- `attention_method="dense"` is correctly passed when constructing `SapiensPose3D` in `main()`.
- No bugs or deviations found.

Full review: `runs/idea002/design001/code_review.md`

---

## Entry 2

**Design ID:** design002
**Design Name:** Soft Kinematic Mask
**Reviewer:** Experiment Designer
**Review Date:** 2026-04-02
**Verdict:** APPROVED

### Summary

The `train.py` implementation precisely matches all specifications in `design.md`:

- `HOP_DIST` is built at module level via BFS with `fill_value=num_joints`, `dtype=torch.long`, shape `(70, 70)` — exact match.
- `Pose3DHead.__init__` computes `soft_bias = HOP_DIST.float() * math.log(0.5)` and registers it via `self.register_buffer("soft_bias", soft_bias)` only when `attention_method == "soft_kinematic_mask"` — exact match to spec formula.
- `Pose3DHead.forward` calls `self.decoder(queries, memory, tgt_mask=self.soft_bias)` for the soft mask branch and `tgt_mask=None` otherwise. `memory_mask` is not used. Shape `(70, 70)` broadcasts correctly.
- All head parameters match: `num_joints=70`, `hidden_dim=256`, `num_heads=8`, `num_layers=4`, `dropout=0.1`, `batch_first=True`, `norm_first=True`.
- All training hyperparameters match: `epochs=20`, `lr_backbone=1e-5`, `lr_head=1e-4`, `weight_decay=0.03`, `warmup_epochs=3`, `grad_clip=1.0`, `lambda_depth=0.1`, `lambda_uv=0.2`, `amp=False`.
- `attention_method="soft_kinematic_mask"` is correctly passed when constructing `SapiensPose3D` in `main()`.
- No NaN risk: all bias values are finite (min ≈ −48.5 for d=70).
- No bugs or deviations found.

Full review: `runs/idea002/design002/code_review.md`

---

## Entry 3

**Design ID:** design003
**Design Name:** Hard Kinematic Mask
**Reviewer:** Experiment Designer
**Review Date:** 2026-04-02
**Verdict:** APPROVED

### Summary

The `train.py` implementation precisely matches all specifications in `design.md`:

- `HOP_DIST` is built at module level via BFS with `fill_value=num_joints`, `dtype=torch.long`, shape `(70, 70)` — exact match.
- Hard mask precomputation in `Pose3DHead.__init__` (when `attention_method="hard_kinematic_mask"`) matches the spec's pseudocode verbatim: `HOP_RADIUS=2`, `allowed=(d<=2)`, NaN guard via `fully_masked_rows = ~allowed.any(dim=1)` setting isolated rows to True, `hard_mask = torch.zeros(70,70,float32)` with `-inf` for blocked entries, registered via `self.register_buffer("hard_mask", hard_mask)`.
- `Pose3DHead.forward` calls `self.decoder(queries, memory, tgt_mask=self.hard_mask)` for the hard mask branch. `memory_mask` is left as `None`. Cross-attention is unchanged.
- No warmup or annealing for the mask — hard masking is applied from epoch 0. The LR warmup schedule applies only to the optimizer, not the mask.
- All head parameters match: `num_joints=70`, `hidden_dim=256`, `num_heads=8`, `num_layers=4`, `dropout=0.1`, `batch_first=True`, `norm_first=True`.
- All training hyperparameters match: `epochs=20`, `lr_backbone=1e-5`, `lr_head=1e-4`, `weight_decay=0.03`, `warmup_epochs=3`, `grad_clip=1.0`, `lambda_depth=0.1`, `lambda_uv=0.2`, `amp=False`.
- `attention_method="hard_kinematic_mask"` is correctly passed when constructing `SapiensPose3D` in `main()`.
- No bugs or deviations found.

Full review: `runs/idea002/design003/code_review.md`
