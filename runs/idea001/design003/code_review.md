# Code Review — idea001 / design003 — late_cross_attention

**Date:** 2026-04-02  
**Reviewer:** Designer  
**Result:** APPROVED

---

## Review Scope

Verified that `runs/idea001/design003/train.py` precisely implements every requirement in `runs/idea001/design003/design.md`.

---

## Checklist

### DepthTokenizer

| Requirement | Implementation | Status |
|---|---|---|
| `Conv2d(1, 64, kernel_size=16, stride=16, padding=2)` | Lines 445–447, exact match | ✓ |
| `LayerNorm(64)` | Line 448 | ✓ |
| `flatten(2).transpose(1,2)` → (B,960,64) | Lines 455–456 | ✓ |
| Conv2d weight and bias zero-init | Lines 450–451 | ✓ |
| `depth_norm` default init (weight=1, bias=0) | LayerNorm default — no override | ✓ |

### DepthCrossAttention

| Requirement | Implementation | Status |
|---|---|---|
| `q_proj: Linear(1024, 256, bias=True)` | Line 488 | ✓ |
| `k_proj: Linear(64, 256, bias=True)` | Line 489 | ✓ |
| `v_proj: Linear(64, 256, bias=True)` | Line 490 | ✓ |
| `out_proj: Linear(256, 1024, bias=True)` | Line 491 | ✓ |
| `attn_drop: Dropout(0.1)` | Line 492 | ✓ |
| `norm_q: LayerNorm(1024)` | Line 494 | ✓ |
| `norm_d: LayerNorm(64)` | Line 495 | ✓ |
| `ffn_norm: LayerNorm(1024)` | Line 496 | ✓ |
| FFN: Linear(1024,4096)→GELU→Dropout→Linear(4096,1024)→Dropout | Lines 497–503 | ✓ |

### Initialization

| Requirement | Implementation | Status |
|---|---|---|
| `q_proj, k_proj, v_proj`: Xavier uniform | Lines 510–511 | ✓ |
| `out_proj`: zeros (weight and bias) | Lines 513–514 | ✓ |
| FFN Linear layers: Xavier uniform | Lines 516–519 | ✓ |
| LayerNorms: default (weight=1, bias=0) | Comment line 520, no override | ✓ |
| `depth_patch_embed` Conv2d: zeros | Lines 450–451 | ✓ |

### Forward Pass — DepthCrossAttention

| Requirement | Implementation | Status |
|---|---|---|
| Pre-norm on RGB tokens (`norm_q`) before Q projection | Lines 528–531 | ✓ |
| Pre-norm on depth tokens (`norm_d`) before K/V projection | Lines 529, 532–533 | ✓ |
| Multi-head reshape: `(B, N, num_heads, head_dim).transpose(1,2)` | Lines 536–538 | ✓ |
| Scaled dot-product attention with `scale=head_dim**-0.5` | Lines 542–546 (uses `F.scaled_dot_product_attention` per spec note) | ✓ |
| Residual: `x = x + ctx` | Line 550 | ✓ |
| FFN: pre-norm + residual | Line 553 | ✓ |
| Returns (B, N, rgb_dim) | Line 555 | ✓ |

### SapiensBackboneLateFusion

| Requirement | Implementation | Status |
|---|---|---|
| ViT instantiated with `in_channels=3` | Line 578 | ✓ |
| `DepthTokenizer` instantiated with correct params | Lines 582–585 | ✓ |
| `DepthCrossAttention` instantiated with correct params | Lines 586–589 | ✓ |
| Forward: ViT(rgb) → flatten → DepthTokenizer(depth) → CrossAttn → reshape | Lines 629–648 | ✓ |
| Feature map shape `(B, 1024, 40, 24)` in, same shape out | Lines 634, 647 | ✓ |
| Gradient checkpointing used for ViT layers and cross-attn (training only) | Lines 613, 641–644 | ✓ (consistent with spec spirit; not prohibited) |

### SapiensPose3D Wrapper

| Requirement | Implementation | Status |
|---|---|---|
| Splits `(B, 4, H, W)` input → rgb `(B, 3)` + depth `(B, 1)` | Lines 796–798 | ✓ |
| Passes rgb and depth separately to backbone | Line 798 | ✓ |
| Head receives `(B, 1024, 40, 24)` feature map unchanged | Lines 798–799 | ✓ |

### Configuration (_Cfg)

| Parameter | Required | Actual | Status |
|---|---|---|---|
| `arch` | `sapiens_0.3b` | `sapiens_0.3b` | ✓ |
| `fusion_strategy` | `late_cross_attention` | `late_cross_attention` | ✓ |
| `img_h × img_w` | `640 × 384` | `640 × 384` | ✓ |
| `depth_embed_dim` | `64` | `64` (hardcoded at model instantiation line 1023) | ✓ |
| `qk_dim` | `256` | `256` | ✓ |
| `num_heads` | `8` | `8` | ✓ |
| `epochs` | `20` | `20` | ✓ |
| `lr_backbone` | `1e-5` | `1e-5` | ✓ |
| `lr_depth_adapter` | `1e-4` | `1e-4` | ✓ |
| `lr_head` | `1e-4` | `1e-4` | ✓ |
| `weight_decay` | `0.03` | `0.03` | ✓ |
| `warmup_epochs` | `3` | `3` | ✓ |
| `grad_clip` | `1.0` | `1.0` | ✓ |
| `amp` | `False` | `False` | ✓ |
| `drop_path` | `0.1` | `0.1` | ✓ |
| `head_hidden` | `256` | `256` | ✓ |
| `head_num_heads` | `8` | `8` | ✓ |
| `head_num_layers` | `4` | `4` | ✓ |
| `head_dropout` | `0.1` | `0.1` | ✓ |
| `lambda_depth` | `0.1` | `0.1` | ✓ |
| `lambda_uv` | `0.2` | `0.2` | ✓ |
| `splits_file` | `splits_rome_tracking.json` | absolute path to same file | ✓ |
| `output_dir` | `runs/idea001/design003` | absolute path to same dir | ✓ |

### Optimizer (3 Parameter Groups)

| Group | Required | Implementation | Status |
|---|---|---|---|
| Backbone ViT | `lr=1e-5`, `wd=0.03` | `model.backbone.vit.parameters()`, lr=1e-5 | ✓ |
| Depth adapter | `lr=1e-4`, `wd=0.03` | `depth_tokenizer + depth_cross_attn params`, lr=1e-4 | ✓ |
| Head | `lr=1e-4`, `wd=0.03` | `model.head.parameters()`, lr=1e-4 | ✓ |
| `weight_decay=0.03` global | ✓ | AdamW kwarg | ✓ |

### Loss Function

| Requirement | Implementation | Status |
|---|---|---|
| `smooth_l1(pred_joints[:, BODY_IDX], gt_joints[:, BODY_IDX], beta=0.05)` | `pose_loss(out["joints"][:, BODY_IDX], joints[:, BODY_IDX])` (pose_loss is smooth_l1 beta=0.05 from infra) | ✓ |
| `+ 0.1 * smooth_l1(pred_pelvis_depth, gt_pelvis_depth)` | `+ args.lambda_depth * l_dep` (lambda_depth=0.1) | ✓ |
| `+ 0.2 * smooth_l1(pred_pelvis_uv, gt_pelvis_uv)` | `+ args.lambda_uv * l_uv` (lambda_uv=0.2) | ✓ |

### CSV Headers / Logging

| Requirement | Implementation | Status |
|---|---|---|
| `logger.log` keys match `_CSV_FIELDNAMES` | Fields: epoch, lr_backbone, lr_head, train_m dict, val_m dict, epoch_time — all present in infra `_CSV_FIELDNAMES`; `extrasaction="ignore"` handles any extras | ✓ |
| iter_logger fields match `_ITER_CSV_FIELDNAMES` | Fields logged: epoch, iter, loss, loss_pose, loss_depth, loss_uv, mpjpe_body, pelvis_err, mpjpe_weighted — exact match | ✓ |

### Pretrained Weight Loading

| Requirement | Implementation | Status |
|---|---|---|
| Loads 3-ch ViT weights without modification | load_sapiens_pretrained: remaps `backbone.vit.*`, loads cleanly | ✓ |
| Skips DepthTokenizer and DepthCrossAttention from checkpoint | Lines 743–744: explicit skip for `backbone.depth_tokenizer.*` and `backbone.depth_cross_attn.*` | ✓ |

---

## Issues Found

None.

---

## Summary

The Builder's `train.py` precisely implements the `late_cross_attention` design spec. All architectural components (`DepthTokenizer`, `DepthCrossAttention`, `SapiensBackboneLateFusion`, `SapiensPose3D`) match the spec exactly. Initialization strategy (zeros for Conv2d and out_proj, Xavier for q/k/v and FFN), optimizer groups, LR schedule, loss formula, hyperparameters, and CSV logging are all correct. The use of `F.scaled_dot_product_attention` in place of the manual QKV loop is explicitly permitted by the spec notes.

**APPROVED**
