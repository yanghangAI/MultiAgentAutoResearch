
---

## Entry: idea001 / design001 — Designer Review (2026-04-02)

**Design_ID:** design001  
**Reviewer:** Designer  
**Result:** APPROVED

**Summary:**  
All parameters, equations, and architectural requirements from `design.md` are faithfully reproduced in `train.py`. Verified: 4-channel early fusion via `torch.cat([rgb, depth], dim=1)`, mean-init for the 4th patch-embed channel, correct loss formula (`smooth_l1 beta=0.05` with `lambda_depth=0.1`, `lambda_uv=0.2`), AdamW two-group optimizer (`lr_backbone=1e-5`, `lr_head=1e-4`, `weight_decay=0.03`), linear warmup 3 epochs + cosine decay, all hyperparameters matching the config table, and `fusion_strategy = "early_4ch"` label added to `_Cfg`. No bugs or deviations found.

Full review: `runs/idea001/design001/code_review.md`

---

## Entry: idea001 / design002 — Designer Review (2026-04-02)

**Design_ID:** design002  
**Reviewer:** Designer  
**Result:** APPROVED

**Summary:**  
All parameters, equations, and architectural requirements from `design.md` are faithfully reproduced in `train.py`. Verified: `DepthProjector` with `Conv2d(1, 1024, kernel_size=16, stride=16, padding=2)` and zeros-init, `LayerNorm(1024)` with default init; `SapiensBackboneMidFusion` with standard 3-channel ViT (`in_channels=3`), depth injection at `i==12` (after block 11, before block 12) as additive bias; `SapiensPose3D` wrapper correctly splitting 4-channel input before routing rgb and depth separately to backbone; 3 AdamW parameter groups (`lr_backbone=1e-5`, `lr_depth_proj=1e-4`, `lr_head=1e-4`, `weight_decay=0.03`); linear warmup 3 epochs + cosine decay; all hyperparameters matching the config table; `fusion_strategy = "mid_fusion"` label in `_Cfg`; correct loss formula with `lambda_depth=0.1` and `lambda_uv=0.2`. No bugs or deviations found.

Full review: `runs/idea001/design002/code_review.md`

---

## Entry: idea001 / design003 — Designer Review (2026-04-02)

**Design_ID:** design003  
**Reviewer:** Designer  
**Result:** APPROVED

**Summary:**  
All parameters, equations, and architectural requirements from `design.md` are faithfully reproduced in `train.py`. Verified: `DepthTokenizer` with `Conv2d(1, 64, kernel_size=16, stride=16, padding=2)` and zeros-init for weight and bias; `DepthCrossAttention` with correct q/k/v/out_proj dimensions (1024→256, 64→256, 64→256, 256→1024), Xavier uniform on q/k/v and FFN, zeros on out_proj; `SapiensBackboneLateFusion` with standard 3-channel ViT, correct forward pass (ViT→flatten→DepthTokenizer→CrossAttn→reshape); `SapiensPose3D` wrapper correctly splitting 4-channel input; 3 AdamW parameter groups (`lr_backbone=1e-5`, `lr_depth_adapter=1e-4`, `lr_head=1e-4`, `weight_decay=0.03`); linear warmup 3 epochs + cosine decay; all hyperparameters matching the config table; `fusion_strategy = "late_cross_attention"` in `_Cfg`; correct loss formula with `lambda_depth=0.1` and `lambda_uv=0.2`; pretrained weight loading skips depth adapter modules correctly. The use of `F.scaled_dot_product_attention` is explicitly permitted by the spec. No bugs or deviations found.

Full review: `runs/idea001/design003/code_review.md`

---
