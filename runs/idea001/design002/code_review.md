# Code Review — idea001 / design002 (mid_fusion)

**Design_ID:** design002  
**Reviewer:** Designer  
**Date:** 2026-04-02  
**Result:** APPROVED

---

## Checklist

### DepthProjector
- [x] `Conv2d(1, embed_dim=1024, kernel_size=16, stride=16, padding=2)` — matches spec exactly.
- [x] `LayerNorm(embed_dim)` — present as `depth_norm`.
- [x] Zero-initialization for both `depth_patch_embed.weight` and `depth_patch_embed.bias` (`nn.init.zeros_`).
- [x] LayerNorm uses default init (weight=1, bias=0) — default PyTorch behavior, no override.
- [x] Forward: `depth_patch_embed(depth)` → flatten(2).transpose(1,2) → depth_norm → `(B, 960, 1024)`. Matches spec.

### SapiensBackboneMidFusion
- [x] `VisionTransformer` instantiated with `in_channels=3`, `patch_size=16`, `patch_cfg=dict(padding=2)`, `final_norm=True`, `with_cls_token=False`, `out_type="featmap"`. All correct for standard 3-channel loading.
- [x] Injection point: `INJECT_BEFORE = 12`; loop `for i, block in enumerate(vit.layers): if i == self.INJECT_BEFORE: x = x + self.depth_proj(depth)`. Correctly injects after block 11, before block 12 executes.
- [x] Manual ViT forward iterates `vit.layers`, applies positional embedding via `resize_pos_embed`, dropout, and pre_norm as expected.
- [x] Final LayerNorm applied at last block using `vit.ln1` — consistent with design spec (with caveat noted in design.md that attribute name may vary; implementation uses `vit.ln1` applied after the last block, inside the loop, which is correct for mmpretrain's `final_norm=True` path).
- [x] Reshape: `x.transpose(1,2).reshape(B, embed_dim, n_h, n_w)` using dynamic `patch_resolution` — functionally equivalent to the spec's fixed `(40, 24)` and more robust.

### Weight Loading
- [x] Standard 3-channel checkpoint loaded without any channel expansion — correct.
- [x] `backbone.depth_proj.*` parameters explicitly skipped during checkpoint loading (zero-init preserved).
- [x] Positional embedding interpolated if spatial resolution differs.

### SapiensPose3D (full model wrapper)
- [x] Accepts `(B, 4, H, W)` tensor, splits into `rgb = x[:, :3]` and `depth = x[:, 3:]`, passes both separately to `SapiensBackboneMidFusion.forward(rgb, depth)`. Matches design requirement ("pass rgb and depth separately to backbone").

### Config (_Cfg)
- [x] `arch = "sapiens_0.3b"`
- [x] `fusion_strategy = "mid_fusion"`
- [x] `img_h = 640`, `img_w = 384`
- [x] `head_hidden = 256`, `head_num_heads = 8`, `head_num_layers = 4`, `head_dropout = 0.1`
- [x] `drop_path = 0.1`
- [x] `epochs = 20`
- [x] `batch_size = BATCH_SIZE` (from infra.py constant = 4)
- [x] `accum_steps = ACCUM_STEPS` (from infra.py constant = 8)
- [x] `lr_backbone = 1e-5`
- [x] `lr_head = 1e-4` (also used for depth_proj group)
- [x] `weight_decay = 0.03`
- [x] `warmup_epochs = 3`
- [x] `grad_clip = 1.0`
- [x] `amp = False`
- [x] `lambda_depth = 0.1`, `lambda_uv = 0.2`
- [x] `splits_file = "splits_rome_tracking.json"` (absolute path used)
- [x] `output_dir = "runs/idea001/design002"` (absolute path used)

### Optimizer (3 parameter groups)
- [x] Group 1: `model.backbone.vit.parameters()`, `lr = args.lr_backbone = 1e-5`
- [x] Group 2: `model.backbone.depth_proj.parameters()`, `lr = args.lr_head = 1e-4` — matches spec's `lr_depth_proj = 1e-4`
- [x] Group 3: `model.head.parameters()`, `lr = args.lr_head = 1e-4`
- [x] All groups share `weight_decay = 0.03`

### LR Schedule
- [x] `get_lr_scale`: linear warmup over `warmup_epochs=3`, then cosine decay to 0. Applied proportionally to all groups via `initial_lr` ratios. Matches design spec.

### Loss
- [x] `loss = pose_loss(joints[BODY_IDX]) + 0.1 * pose_loss(pelvis_depth) + 0.2 * pose_loss(pelvis_uv)`. Matches `smooth_l1(beta=0.05)` via the shared `pose_loss` utility (same as design001 and baseline).

### Training Loop
- [x] `x = torch.cat([rgb, depth], dim=1)` passed to `model(x)`, which internally splits and routes correctly.
- [x] Gradient accumulation over `accum_steps` with grad clip and scaler.

---

## Summary

The implementation in `train.py` faithfully and completely reproduces all architectural, mathematical, and configuration requirements specified in `design.md` for the mid-fusion strategy. No bugs, omissions, or deviations were found.
