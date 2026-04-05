# Review: Design 003 — Hard Kinematic Mask

**Design_ID:** design003
**Review Round:** 2 (revised)
**Verdict:** APPROVED

## Summary

The revision fully addresses all five issues raised in Round 1. The target sub-layer, NaN guard, kinematic graph construction, tensor shape, buffer registration, and warmup decision are all now unambiguously specified with working code. The Proxy Environment Builder can implement this design without guessing.

## Checklist Against Round 1 Issues

### Issue 1 (Which attention sub-layer): RESOLVED
The design explicitly states: self-attention sub-layer via `tgt_mask` in `nn.TransformerDecoder`. Cross-attention (`memory_mask`) is left as `None`. Applied at every decoder layer.

### Issue 2 (Critical NaN risk — fully masked rows): RESOLVED
The design provides an explicit two-step NaN guard:
1. Build `allowed = (HOP_DIST <= 2)`. The diagonal is always `d[i,i]=0 <= 2`, so every joint always allows attention to itself.
2. Check `fully_masked_rows = ~allowed.any(dim=1)` and set those rows to all-True before constructing the float mask.

This correctly handles truly disconnected joints (if any). The design also notes that in practice, the diagonal guarantee means no row is ever fully masked given the BFS initialization `dist[src,src]=0`, making the guard defensive rather than critical — but its presence is correct and does not hurt.

### Issue 3 (Kinematic graph undefined): RESOLVED
BFS on `SMPLX_SKELETON` from `infra.py` over 70 active joints is confirmed, using the shared `HOP_DIST` module-level constant defined in Design 1.

### Issue 4 (Tensor shape and buffer registration): RESOLVED
Mask shape is `(70, 70)` float32. `self.register_buffer("hard_mask", hard_mask)` is called in `__init__`. PyTorch's `nn.MultiheadAttention` broadcasts `(T, T)` attn_mask over batch and heads correctly.

### Issue 5 (Warmup/annealing): RESOLVED
The design explicitly states: "Hard masking from epoch 0, no warmup or annealing schedule." The rationale (anatomical constraints as a deliberate design choice, gradient restriction as a feature) is documented so the Builder does not add a schedule.

## Additional Checks

- **NaN guard logic correctness:** The code sets `allowed[fully_masked_rows, :] = True` before constructing `hard_mask` with `hard_mask[~allowed] = float("-inf")`. Rows that were fully-masked become all-True, producing all-0.0 in the float mask (dense attention). This is mathematically correct.
- **Buffer registration:** `register_buffer` ensures device placement and checkpoint inclusion without optimizer updates. Correct.
- **Training budget:** 20 epochs, batch 4, single GPU — within constraint. No additional learnable parameters.
- **No `infra.py` constants modified.**
- **Applied at all 4 decoder layers** via the single `self.decoder(...)` call — correct for PyTorch's `nn.TransformerDecoder` which applies `tgt_mask` at every layer internally.

## Verification of Disconnected Joint Handling

From `infra.py`, joints at original indices 60-75 (non-face surface landmarks: toes, heels, fingertips) are absent from `_SMPLX_BONES_RAW`. These are isolated nodes in `SMPLX_SKELETON`. However, their `HOP_DIST[i,i]=0`, so the diagonal is always in the 2-hop neighborhood. The guard `fully_masked_rows` will be empty in practice, but the code is correct regardless.

## Implementability Confirmation

The Proxy Environment Builder can implement this design fully:
- During `Pose3DHead.__init__` (for `attention_method="hard_kinematic_mask"`): run the 3-step precomputation (build `allowed`, apply NaN guard, convert to float mask) and call `self.register_buffer("hard_mask", hard_mask)`.
- In `forward`: call `self.decoder(queries, memory, tgt_mask=self.hard_mask)`.
- No warmup, no annealing — hard mask applied from epoch 0.
- All other training setup is identical to `baseline.py`.
