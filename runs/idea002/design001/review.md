# Review: Design 001 — Baseline Dense (Control)

**Design_ID:** design001
**Review Round:** 2 (revised)
**Verdict:** APPROVED

## Summary

The revision fully addresses all three issues raised in Round 1. The design is now specified at the level required for the Proxy Environment Builder to implement `proxy_train.py` without ambiguity or guessing.

## Checklist Against Round 1 Issues

### Issue 1 (API hook for `attention_method`): RESOLVED
The revised design explicitly states that `Pose3DHead.__init__` accepts `attention_method: str` (default `"dense"`) and that `"dense"` maps to `self.decoder(queries, memory, tgt_mask=None)`. This confirms identical numerical behavior to `baseline.py`.

### Issue 2 (Optimizer hyperparameters): RESOLVED
The revised design provides a complete optimizer table and code snippet with the correct values (`lr_backbone=1e-5`, `lr_head=1e-4`, `weight_decay=0.03`) and explicitly confirms these are identical to `baseline.py`. The earlier confusion with `lr=5e-4, weight_decay=0.1` is resolved.

### Issue 3 (Kinematic graph as shared module-level constant): RESOLVED
The revised design includes the full `_build_hop_distance_matrix` function with BFS on `SMPLX_SKELETON` from `infra.py` and defines `HOP_DIST` at module level. The sentinel value of `NUM_JOINTS` (=70) for unreachable pairs is correctly documented.

## Additional Checks

- Training budget: 20 epochs, batch 4, single GPU — within constraint.
- No `infra.py` constants modified.
- `HOP_DIST` computed at import time (not per forward pass) — correct.
- Isolated surface landmark joints (toes/heels/fingertips, original indices 60-75, not in `_SMPLX_BONES_RAW`) will have sentinel hop distance 70 to all other joints, and 0 to themselves. This is fine for the control design which does not use the graph.

## Implementability Confirmation

The Proxy Environment Builder can implement this design fully from the specification:
- Instantiate `Pose3DHead(attention_method="dense")`.
- Call `self.decoder(queries, memory, tgt_mask=None)` in `forward`.
- Define `HOP_DIST` at module level as documented.
- All other training setup (loss, optimizer, schedule, data) is identical to `baseline.py`.
