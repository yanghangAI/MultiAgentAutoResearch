# Architect Review — design003 (`late_cross_attention`)

**Date:** 2026-04-02  
**Verdict:** APPROVED (with implementation notes for Builder)

---

## Summary

Design003 proposes a late-fusion architecture where the Sapiens ViT backbone processes only 3-channel RGB (unchanged from pretrained), and a small `DepthCrossAttention` adapter module integrates depth into the backbone output token sequence before the `Pose3DHead`. The approach is architecturally sound, well-motivated, and clearly differentiated from design001 (early 4-ch) and design002 (mid-block injection).

---

## Mathematical Checks

### Conv2d output shape (DepthTokenizer)

`Conv2d(1, 64, kernel_size=16, stride=16, padding=2)` on input `(B, 1, 640, 384)`:

- Height: floor((640 + 2×2 - 16) / 16) + 1 = floor(39.25) + 1 = **40** ✓
- Width: floor((384 + 2×2 - 16) / 16) + 1 = floor(23.25) + 1 = **24** ✓

Output: `(B, 64, 40, 24)` → flatten + transpose → `(B, 960, 64)`. Correct.

### Attention head dimension

`qk_dim = 256`, `num_heads = 8` → `head_dim = 32`. Scale = `32^{-0.5}` = 0.177. Correct.

### Attention matrix size

`(B, num_heads, N, N) = (4, 8, 960, 960)`.  
Actual memory: 4 × 8 × 960 × 960 × 4 bytes ≈ **117 MB** (fp32).

**Note for Builder:** The design document states "~28MB at B=4" — this is a factor-of-4 error (appears to have omitted the batch dimension B=4 from the calculation). The correct figure is ~117MB. This is still well within the 11GB VRAM budget and does not affect the validity of the design, but the Builder should use the correct figure for memory planning.

### FFN parameter count

FFN: Linear(1024, 4096) + Linear(4096, 1024) + biases = 1024×4096 + 4096 + 4096×1024 + 1024 = 8,390,656 + 5,120 = 8,395,776 ≈ **8.4M**. Consistent with the design's ~8.4M estimate. ✓

### Total parameter count

~307M (ViT) + ~9M (depth adapter) + ~1M (head) ≈ **317M**. ✓

---

## Zero-Init Chain — Correctness and Caveat

The design claims: *"epoch-0 behavior is identical to a pure-RGB model."*

This claim is **partially inaccurate** and the Builder must understand the distinction:

- The cross-attention residual (`ctx = out_proj(...)`) is zero at epoch 0 because `DepthTokenizer.depth_patch_embed` weights are zero → `d = 0` → `V = 0` → `ctx = 0` → `out_proj(0) = 0`. The residual `x = x + ctx` leaves `x` unchanged. ✓
- However, the **FFN sub-layer** `x = x + self.ffn(self.ffn_norm(x))` runs unconditionally on `x` (the RGB token sequence). The FFN weights are initialized with Xavier uniform (non-zero). Therefore, at epoch 0, the FFN applies a non-trivial transformation to the RGB token sequence.

**Implication:** At epoch 0, the model is NOT equivalent to a pure-RGB baseline — the FFN in `DepthCrossAttention` modifies the token sequence even when depth is all-zeros. This is a minor point and does not invalidate the design (the FFN acts as a learned adapter from the first forward pass, which is fine), but the Builder should not assume epoch-0 loss will match a pure-RGB baseline exactly. The initialization is a "warm-start with zero cross-attention" rather than a "true identity initialization."

If a true identity initialization at epoch 0 is desired, the FFN's first Linear layer (`Linear(1024, 4096)`) would also need zero initialization — but this is left as a design choice and is **not required for approval**.

---

## Budget Assessment (20 epochs, single 1080Ti, 11GB VRAM)

| Component | VRAM estimate |
|-----------|--------------|
| ViT backbone activations (fp32, B=4) | ~4–5 GB (same as design001/002) |
| DepthCrossAttention attention matrix | ~117 MB |
| DepthCrossAttention FFN activations | ~60 MB (B=4, N=960, hidden=4096) |
| Depth adapter parameters (fp32) | ~36 MB (~9M params) |
| Gradients (same as params) | ~36 MB |
| Optimizer state (AdamW, 2× params) | ~72 MB for adapter; backbone occupies ~2.4 GB |
| **Total estimate** | **~6–8 GB** |

**Assessment:** Budget is safe. `AMP=False` is conservative but appropriate since the 1080Ti has limited fp16 throughput for this workload. The design's choice not to enable AMP is consistent with design001 and design002.

---

## Implementation Risk Assessment

### Low risk
1. **3-channel ViT checkpoint loading:** Standard pretrained weights load cleanly with no weight surgery. This is the simplest checkpoint loading scenario of all three designs. ✓
2. **Pose3DHead unchanged:** The head receives the same `(B, 1024, 40, 24)` shape as baseline. No head changes needed. ✓
3. **Loss function unchanged:** Same smooth_l1 + lambda_depth + lambda_uv as design001/002. ✓

### Medium risk (flag for Builder)
4. **ViT `forward` return format:** Confirm that `self.vit(rgb)` returns the spatial feature map `(B, 1024, 40, 24)` (i.e., that the ViT's internal `forward` method applies the final LayerNorm internally and returns a 4D spatial tensor, not a flat token sequence). This was flagged in design002 as well — the Builder should verify the attribute name for the final norm (`ln1` vs `norm`) is consistent and applied inside the ViT's own `forward`. If the ViT returns tokens `(B, 960, 1024)` directly, `SapiensBackboneLateFusion.forward` must reshape before proceeding.
5. **`scaled_dot_product_attention` scale kwarg:** If PyTorch 2.1+ is available, the `scale` kwarg can be passed directly. If PyTorch 2.0 (where `scale` kwarg is unavailable), the Builder should pre-scale Q manually: `Q = Q * (32 ** -0.5)` before calling `F.scaled_dot_product_attention`. Verify the PyTorch version in the conda environment (`hang` env).
6. **`drop_path=0.1` in config table:** This parameter appears in the config table but is not described in the architecture section. It is presumably applied to the ViT backbone blocks (stochastic depth in ViT), not to the `DepthCrossAttention` block. The Builder should confirm this is passed to the ViT constructor (if the ViT constructor accepts it) or ignored. Do not add drop_path to `DepthCrossAttention` unless explicitly intended.

---

## Design Quality Assessment

- **Novelty vs. design001/002:** Clearly differentiated. design001 modifies the patch embed (4-ch input), design002 injects depth mid-backbone (block 12), design003 leaves the backbone entirely untouched and uses a post-backbone cross-attention adapter. These three designs cover early, mid, and late fusion, forming a coherent ablation study. ✓
- **Hypothesis clarity:** Well-stated — keeping the ViT backbone on pure RGB maximizes the benefit of the ImageNet+HMR pretrained features, while the cross-attention adapter learns depth-to-pose correlations independently. ✓
- **QKV assignment rationale:** Correct and well-reasoned. RGB as queries, depth as keys/values means RGB feature vectors are the primary carrier and depth modulates them. ✓
- **Depth embed dim (64 vs 1024):** Compact and well-justified. The 9M adapter is appropriately lightweight relative to the 307M backbone. ✓

---

## Verdict

**APPROVED.** The design is mathematically correct, fits within the 20-epoch proxy budget on a single 1080Ti, and is architecturally sound. The key implementation notes for the Builder are:

1. The attention matrix is ~117MB at B=4 (not ~28MB as stated in the design).
2. At epoch 0 the FFN sub-layer is non-trivial — do not assume perfect parity with a pure-RGB baseline.
3. Verify the ViT `forward` return shape before the `flatten + transpose` step.
4. Confirm PyTorch version before using the `scale` kwarg in `F.scaled_dot_product_attention`.
5. Clarify where `drop_path=0.1` is applied (backbone ViT, not the depth adapter).
