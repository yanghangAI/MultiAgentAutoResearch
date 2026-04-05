# Review Log — idea001 (RGB-D Modality Fusion Strategy)

---

## Entry: design001 — `early_4ch`

**Date:** 2026-04-02  
**Verdict:** APPROVED

Design 001 reproduces the baseline exactly as a controlled anchor for the fusion strategy comparison. All hyperparameters, shapes, and loss terms match `baseline.py` and `infra.py` constants. Patch embedding 4-channel init is mathematically sound. Budget is safe (architecturally identical to baseline). No implementation risks identified.

Minor note: README states auxiliary losses were removed, but `baseline.py` retains them — design correctly follows the code, not the stale README.

Full review: `runs/idea001/design001/review.md`

---

## Entry: design002 — `mid_fusion`

**Date:** 2026-04-02  
**Verdict:** APPROVED

Design002 proposes injecting a zero-initialized learned depth bias into the Sapiens ViT token stream at the midpoint (after block 11, before block 12). The 3-channel RGB patch embed loads from the standard pretrained checkpoint without weight surgery. Spatial math for the DepthProjector Conv2d (padding=2, stride=16) is verified correct — output is 40×24=960 tokens matching ViT token count. Zero-init of the depth pathway ensures epoch-0 parity with a pure-RGB forward pass. Budget is safe: DepthProjector adds negligible parameters and no additional activation memory vs. baseline. Three medium/low-risk implementation issues flagged for Builder: (1) confirm final LayerNorm attribute name (`ln1` vs `norm`), (2) verify `vit.patch_embed()` returns `(B, N, C)` not `(B, C, H, W)` when called directly, (3) ensure pos_embed interpolation is called in the 3-ch weight loader. All are verifiable at implementation time and do not invalidate the design.

Full review: `runs/idea001/design002/review.md`

---

## Entry: design003 — `late_cross_attention`

**Date:** 2026-04-02  
**Verdict:** APPROVED (with implementation notes for Builder)

Design003 leaves the Sapiens ViT backbone entirely untouched (3-channel RGB, standard pretrained weights loaded cleanly) and adds a `DepthCrossAttention` adapter between the backbone output and the `Pose3DHead`. Conv2d padding math verified: `(640 + 4 - 16)/16 + 1 = 40`, `(384 + 4 - 16)/16 + 1 = 24` → correct 960-token output. Attention matrix VRAM is ~117MB at B=4 (the design document states ~28MB, a factor-of-4 error omitting the batch dimension — flag for Builder but not a safety issue). Budget is safe overall (~6–8GB estimated, AMP=False).

Key implementation notes for Builder: (1) The design's claim of "epoch-0 behavior identical to pure-RGB" is imprecise — the FFN sub-layer (Xavier-initialized, non-zero) runs unconditionally on the RGB token sequence even when the cross-attention residual is zero. Epoch-0 loss will not exactly match a pure-RGB baseline. (2) Verify ViT `forward` return shape (`(B, 1024, 40, 24)` vs flat tokens) before the `flatten + transpose` step. (3) Confirm PyTorch version for `scale` kwarg availability in `F.scaled_dot_product_attention`. (4) `drop_path=0.1` in config table is not described in the architecture — confirm it targets the ViT backbone constructor, not the `DepthCrossAttention` block.

Full review: `runs/idea001/design003/review.md`

---
