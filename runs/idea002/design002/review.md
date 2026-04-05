# Review: Design 002 — Soft Kinematic Mask

**Design_ID:** design002
**Review Round:** 2 (revised)
**Verdict:** APPROVED

## Summary

The revision fully addresses all four issues raised in Round 1. The penalty formula, masking radius, target sub-layer, kinematic graph construction, and NaN safety are all now unambiguously specified. The Proxy Environment Builder can implement this design without guessing.

## Checklist Against Round 1 Issues

### Issue 1 ("Masking Radius: Whole Body" was undefined): RESOLVED
The revised design states explicitly: "No cutoff — the bias is applied globally to all 70×70 pairs." This eliminates the ambiguity.

### Issue 2 (Penalty formula was ambiguous): RESOLVED
The exact formula is specified: `soft_bias[i,j] = HOP_DIST[i,j].float() * math.log(0.5)`, applied as an additive bias to attention logits before softmax. The design confirms this is an additive logit bias (not a post-softmax multiplicative factor). The `LOG_HALF` constant is provided in code.

### Issue 3 (Which attention sub-layer): RESOLVED
The design explicitly states: self-attention sub-layer via `tgt_mask` in `nn.TransformerDecoder`. Cross-attention (`memory_mask`) is not used (left as `None`). Applied at every decoder layer.

### Issue 4 (Kinematic graph undefined): RESOLVED
BFS on `SMPLX_SKELETON` from `infra.py` over 70 active joints is confirmed. Isolated joints (toes, heels, fingertips — original indices 60-75, absent from `_SMPLX_BONES_RAW`) retain sentinel distance 70, yielding a finite bias of `70 * log(0.5) ≈ -48.5`. This is explicitly noted.

## Additional Checks

- **NaN safety:** All bias values are finite (minimum ≈ -48.5 for isolated joints, 0.0 on the diagonal). No `-inf` entries. Softmax is always well-defined. CONFIRMED SAFE.
- **Buffer registration:** `self.register_buffer("soft_bias", soft_bias)` — correct, moves to device with model, excluded from optimizer.
- **Tensor shape:** `(70, 70)` float32, broadcasts correctly over batch and heads in `nn.MultiheadAttention`.
- **Training budget:** 20 epochs, batch 4, single GPU — within constraint. No additional parameters added.
- **No `infra.py` constants modified.**

## Verification of Isolated Joint Handling

From `infra.py`, `ACTIVE_JOINT_INDICES` includes original indices 60-75 (non-face surface landmarks). None of these appear in `_SMPLX_BONES_RAW`, confirming they are isolated nodes in `SMPLX_SKELETON`. With `d[i,i]=0`, their self-attention bias is 0.0 (unpenalized). Cross-joint bias is `70 * log(0.5) ≈ -48.5` (strongly suppressed but finite). The design's analysis is correct.

## Implementability Confirmation

The Proxy Environment Builder can implement this design fully:
- During `Pose3DHead.__init__` (for `attention_method="soft_kinematic_mask"`): compute `soft_bias = HOP_DIST.float() * math.log(0.5)` and call `self.register_buffer("soft_bias", soft_bias)`.
- In `forward`: call `self.decoder(queries, memory, tgt_mask=self.soft_bias)`.
- All other training setup is identical to `baseline.py`.
