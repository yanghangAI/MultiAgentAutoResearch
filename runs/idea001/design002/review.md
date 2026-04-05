# Architect Review — design002 (mid_fusion)

**Idea:** idea001 — RGB-D Modality Fusion Strategy  
**Design:** design002 — Mid-Layer Depth Fusion (`mid_fusion`)  
**Date:** 2026-04-02  
**Verdict:** APPROVED

---

## Summary

Design002 proposes injecting a learned depth bias (zero-initialized) into the ViT token stream at the midpoint (after block 11, before block 12) of the Sapiens 0.3b backbone. The RGB ViT is loaded from the standard 3-channel pretrained checkpoint without any weight surgery, and the DepthProjector starts as a no-op (zero output), preserving epoch-0 parity with a pure-RGB baseline. This is a sound, well-motivated design.

---

## Mathematical Checks

### 1. DepthProjector spatial output — CORRECT
- Input: `(B, 1, 640, 384)`
- Conv2d: `kernel_size=16`, `stride=16`, `padding=2`
- Height out: `floor((640 + 2×2 − 16) / 16) + 1 = floor(628/16) + 1 = 39 + 1 = 40` ✓
- Width out:  `floor((384 + 2×2 − 16) / 16) + 1 = floor(372/16) + 1 = 23 + 1 = 24` ✓
- Tokens: `40 × 24 = 960` — matches ViT token count ✓

### 2. Additive injection shape compatibility — CORRECT
`DepthProjector` output `(B, 960, 1024)` is added to ViT token sequence `(B, 960, 1024)`. No shape mismatch. Positional embedding `(1, 960, 1024)` is applied before injection, so depth bias is added to the post-PE token sequence. This is mathematically equivalent to learning a depth-conditioned residual on top of the existing token representation.

### 3. Zero-init of DepthProjector — SOUND
Zero weight + zero bias on `depth_patch_embed` gives `depth_proj(depth) = LayerNorm(0) = 0` at epoch 0 (since LayerNorm of a zero tensor with weight=1, bias=0 is 0). The model at epoch 0 is exactly a pure-RGB forward pass. Depth gradients grow from zero, protecting the pretrained RGB regime from disruption.

### 4. Loss function — UNCHANGED
Identical to baseline and design001. All loss weight constants (`lambda_depth=0.1`, `lambda_uv=0.2`) match.

### 5. LR schedule — CONSISTENT
Linear warmup (3 epochs) then cosine decay to 0, applied to all 3 optimizer groups via proportional `base_lr` ratios. This is consistent with the baseline's scheduling pattern.

---

## Budget Check

### VRAM
- DepthProjector parameters: `1 × 1024 × 16 × 16 = 262,144` weights (Conv2d) + `1024` LayerNorm params ≈ negligible.
- Activation footprint: identical to design001 (same ViT depth and token count). The single forward pass holds `(B=4, 960, 1024)` activations per block — identical to the existing baseline.
- AMP=False, BATCH_SIZE=4 (infra.py constant, unchanged): budget is safe, well within 11GB.

### Epochs
20 epochs at same throughput as baseline. No additional computation per step (DepthProjector is a single Conv2d + LayerNorm on the small depth map).

---

## Implementation Risks (Builder Must Resolve)

### Risk 1 — Final LayerNorm attribute name (MEDIUM)
The design references `self.vit.ln1` as the final layer norm. In mmpretrain's `VisionTransformer`, when `final_norm=True`, the final norm may be named `self.ln1` or `self.norm` depending on the version installed. **Builder must print/inspect `dict(vit.named_modules())` keys and use the correct attribute name.** A wrong name will silently skip the final norm, causing degraded features.

### Risk 2 — `vit.patch_embed(rgb)` output shape (MEDIUM)
When `VisionTransformer` is constructed with `out_type="featmap"`, this controls the final reshape in `VisionTransformer.forward`, but the `patch_embed` sub-module's own `forward` is independent. In mmpretrain, `AdaptivePadding`+`PatchEmbed` typically returns `(B, N, C)` (already flattened+transposed). However, the Builder must verify this empirically — if `vit.patch_embed` returns `(B, C, H, W)`, the manual forward loop will fail. **Builder must add an assertion: `assert x.ndim == 3 and x.shape == (B, 960, 1024)` immediately after `x = self.vit.patch_embed(rgb)`.**

### Risk 3 — pos_embed broadcast (LOW)
`x + self.vit.pos_embed` requires `pos_embed` shape `(1, 960, 1024)`. The baseline uses `_interp_pos_embed` to resize the checkpoint's pos_embed to match `(40, 24)` patch resolution. The weight loader in design002 must call the same interpolation (skipping the 4-ch expansion). If the pretrained pos_embed is not interpolated, shape mismatch will raise at runtime. **Builder must confirm the loading path calls `_interp_pos_embed` as in `load_sapiens_pretrained`, adapted for 3-channel input.**

### Risk 4 — Train loop API change (LOW, by design)
The baseline concatenates `x = torch.cat([rgb, depth], dim=1)` and calls `model(x)`. Design002 requires `model.backbone(rgb, depth)` with separate tensors. The Builder must update the train and validation loops accordingly. This is clearly specified in the design's implementation notes.

---

## Hyperparameter Review

All hyperparameters are within expected ranges:
- `lr_backbone=1e-5`: conservative, consistent with baseline and design001 ✓
- `lr_depth_proj=1e-4`, `lr_head=1e-4`: appropriate for newly initialized modules ✓
- `weight_decay=0.03`: identical to baseline ✓
- `drop_path=0.1`: identical to baseline ✓
- Head config (hidden=256, heads=8, layers=4, dropout=0.1): identical to baseline ✓
- `epochs=20`, `batch_size=4` (from infra.py), `accum_steps=8` (from infra.py): all compliant ✓
- `amp=False`: correct for 1080Ti (no FP16 tensor cores) ✓
- `splits_file=splits_rome_tracking.json`: consistent with idea001 ✓

---

## Conclusion

Design002 is mathematically sound and budget-compliant. The zero-init strategy for the depth pathway is elegant and principled. The three implementation risks identified are all resolvable at implementation time via simple assertions and attribute inspection — none invalidates the design. The design provides adequate guidance for the Builder.

**APPROVED.**
