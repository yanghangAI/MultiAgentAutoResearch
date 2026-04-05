# Review Log — idea002: Kinematic Attention Masking

---

## design001 — Baseline Dense (Control)

**Verdict:** REJECTED

Design 1 is intended as the dense-attention control (no masking). Training parameters fit the proxy budget. However, it lacks implementation detail needed by the Proxy Environment Builder.

**Issues:**
1. Does not specify how `attention_method` is plumbed into the model class — whether `Pose3DHead` (or a proxy variant) accepts an `attention_method` argument, and that `dense` maps to `tgt_mask=None` in `self.decoder(queries, memory, tgt_mask=None)`.
2. Does not confirm whether optimizer hyperparameters (`lr=5e-4`, `weight_decay=0.1`) are identical to `baseline.py` or intentionally changed.
3. Does not state that the kinematic hop-distance matrix (shared across all 3 designs) is precomputed from `SMPLX_SKELETON` in `infra.py` and stored as a module-level constant.

**Review file:** `runs/idea002/design001/review.md`

---

## design002 — Soft Kinematic Mask

**Verdict:** REJECTED

Design 2 proposes soft penalty masking with 0.5 decay per hop. Training budget is within constraint. Four critical gaps prevent implementation without guessing.

**Issues:**
1. "Masking Radius: Whole Body" is undefined and self-contradictory — must specify whether there is a cutoff or the bias is applied globally to all 70×70 pairs.
2. "0.5 decay per hop" is ambiguous — must specify exact formula (e.g., `tgt_mask[i,j] = d(i,j) * log(0.5)` as an additive logit bias).
3. Does not specify which attention sub-layer receives the mask (self-attention via `tgt_mask`, not cross-attention via `memory_mask`).
4. Does not define the kinematic graph, hop-distance computation (BFS on `SMPLX_SKELETON`), or handling of unreachable/disconnected joint pairs.

**Review file:** `runs/idea002/design002/review.md`

---

## design003 — Hard Kinematic Mask

**Verdict:** REJECTED

Design 3 proposes hard masking within a 2-hop neighborhood. The radius is concrete and budget is within constraint. However, there are critical implementation gaps and one mathematical risk (NaN from fully masked rows).

**Issues:**
1. Does not specify which attention sub-layer receives the mask (must be `tgt_mask` for self-attention in `nn.TransformerDecoder`).
2. Critical NaN risk: disconnected joints produce fully `-inf` rows in softmax. Must require a guard (set fully-masked rows to `0.0`) and confirm the diagonal is always included.
3. Does not define the kinematic graph or confirm BFS on `SMPLX_SKELETON` from `infra.py`.
4. Does not specify mask tensor shape `[num_joints, num_joints]` as a precomputed registered buffer.
5. Does not state whether hard masking is applied from epoch 0 or with a warmup/annealing schedule.

**Review file:** `runs/idea002/design003/review.md`

---

---
## ROUND 2 REVIEWS (2026-04-02)
---

## design001 — Baseline Dense (Control)

**Verdict:** APPROVED

All three Round 1 issues resolved. The `attention_method` API is fully specified (`"dense"` maps to `tgt_mask=None`). Optimizer hyperparameters are confirmed identical to `baseline.py` (`lr_backbone=1e-5`, `lr_head=1e-4`, `weight_decay=0.03`). The `HOP_DIST` module-level constant is defined with complete BFS code over `SMPLX_SKELETON` from `infra.py`. Design is implementable by the Proxy Environment Builder without guessing.

**Review file:** `runs/idea002/design001/review.md`

---

## design002 — Soft Kinematic Mask

**Verdict:** APPROVED

All four Round 1 issues resolved. Masking radius is specified as global (no cutoff, all 70x70 pairs). Formula is unambiguous: `soft_bias[i,j] = HOP_DIST[i,j].float() * math.log(0.5)`, additive logit bias, pre-softmax. Target sub-layer is self-attention via `tgt_mask`. Kinematic graph BFS on `SMPLX_SKELETON` is confirmed. Isolated joints (original indices 60-75, not in `_SMPLX_BONES_RAW`) get finite sentinel bias (`70 * log(0.5) ≈ -48.5`), no NaN risk. Buffer registration correct. Design is implementable without guessing.

**Review file:** `runs/idea002/design002/review.md`

---

## design003 — Hard Kinematic Mask

**Verdict:** APPROVED

All five Round 1 issues resolved. Target sub-layer is self-attention via `tgt_mask`. NaN guard is explicit and correct: `allowed[fully_masked_rows, :] = True` before float mask construction; diagonal `d[i,i]=0` guarantees no row is truly fully-masked in practice. Kinematic graph BFS on `SMPLX_SKELETON` confirmed. Mask shape `(70, 70)` float32, registered as buffer. No warmup — hard masking from epoch 0 explicitly documented. Design is implementable without guessing.

**Review file:** `runs/idea002/design003/review.md`

---
