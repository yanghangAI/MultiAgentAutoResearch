# Review — Design 002 (relative_depth_bias)

**Reviewer:** Architect  
**Date:** 2026-04-03  
**Decision:** APPROVED

## Mathematical Soundness
Additive bias to cross-attention logits is well-established (ALiBi, T5 relative position bias). The bias enters before softmax as a learned scalar offset per (joint, patch) pair, which is mathematically sound. Zero-initialization guarantees exact baseline behavior at epoch 0 — no warm-start disruption.

## Tensor Shape Verification
- `avg_pool2d(depth_ch, 16, 16)`: `(B,1,640,384) → (B,1,40,24)` ✓ (640/16=40, 384/16=24, 40×24=960 ✓)
- `reshape(B,1,-1).permute(0,2,1)`: `(B,960,1)` ✓
- `depth_proj(depth_flat)` with `Linear(1,70)`: `(B,960,70)` ✓
- `.permute(0,2,1)`: `(B,70,960)` ✓
- `.unsqueeze(1).expand(B,8,-1,-1).reshape(B*8,70,960)`: `(B*nH,70,960)` ✓

`attn_mask` shape `(B*nH, tgt_len, src_len)` is correct for `nn.MultiheadAttention` regardless of `batch_first` — PyTorch's `batch_first` only affects query/key/value tensor layout, not the mask shape.

## Parameter Count
`Linear(1,70)`: weight=70, bias=70 → **140 params total**. (Note: the design text is correct; a prior review erroneously stated 1,120 params.)

## Memory Budget
- `depth_bias_expanded` shape `(B*nH,70,960)` = `(32,70,960)` = 2,150,400 floats ≈ **8.6 MB**. (Design states "8.4M floats" — this is a factor-of-4 arithmetic error; actual count is ~2.15M. Conclusion unchanged: well within 11 GB.)
- 140 new params: negligible.

## Initialization & Warm-Start
Zero-init on both weight and bias of `depth_proj` ensures the additive bias is identically zero at initialization. No pretrained backbone or head parameters are modified. Warm-start is fully preserved.

## Optimizer Group Assignment
`DepthAttentionBias` is instantiated inside `Pose3DHead.__init__`, so its parameters are naturally captured by the `head` optimizer group (LR=1e-4, WD=0.03). Backbone remains at LR=1e-5. Correct.

## Builder Notes Completeness
Six explicit implementation notes covering: module definition, manual loop attribute names, `batch_first=True` shape confirmation, forward signature change to pass `depth_ch`, `num_heads` sourcing, and zero-init. Sufficient for unambiguous implementation.

## Risks / Notes for Builder
- Verify `nn.TransformerDecoderLayer` attribute names (`norm1`, `norm2`, `norm3`, `dropout1`, `dropout2`, `dropout3`) against the installed PyTorch version before coding.
- Test with a small synthetic batch (`B=2`) to confirm `attn_mask` shape is accepted without error before running full training.

## Verdict
No mathematical blockers. Tensor shapes verified. Zero-init preserves warm-start. Budget negligible. Builder notes complete and actionable. **APPROVED.**
