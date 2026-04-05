# Review — Design 001 (discretized_depth_pe)

**Reviewer:** Architect  
**Date:** 2026-04-03  
**Decision:** APPROVED

---

## 1. Mathematical Soundness

Decomposed row + col + depth-bucket PE is a valid factored positional embedding (cf. axial PE). At initialization, `depth_emb = 0`, so the net contribution equals `row_emb[i] + col_emb[j]` for patch (i, j), which is a rank-1 approximation of the original 2D `pos_embed`. This is not an exact restoration of the pretrained PE, but it is a principled warm-start: the dominant row/column structure is preserved and the depth term is neutral. No mathematical issues.

---

## 2. Tensor Shape Correctness

| Operation | Shape | Verdict |
|---|---|---|
| `depth_ch = x[:, 3:4]` | `(B, 1, 640, 384)` | ✓ |
| `avg_pool2d(kernel=16, stride=16)` | `(B, 1, 40, 24)` | ✓ — 640/16=40, 384/16=24 |
| `.squeeze(1)` | `(B, 40, 24)` | ✓ |
| `* 16).long().clamp(0,15)` | `(B, 40, 24)` | ✓ |
| `.reshape(B, -1)` | `(B, 960)` | ✓ — 40×24=960 |
| `row_emb[rows].unsqueeze(0)` | `(1, 960, 1024)` | ✓ |
| `col_emb[cols].unsqueeze(0)` | `(1, 960, 1024)` | ✓ |
| `depth_emb[depth_bins_flat]` | `(B, 960, 1024)` | ✓ |
| Sum (broadcasting) | `(B, 960, 1024)` | ✓ |
| `patch_tokens + pe` | `(B, 960, 1024)` | ✓ |

All shapes are correct.

---

## 3. Initialization Strategy

- `row_emb` ← `pe_2d.mean(dim=1)` (mean over 24 columns → `(40, 1024)`) ✓  
- `col_emb` ← `pe_2d.mean(dim=0)` (mean over 40 rows → `(24, 1024)`) ✓  
- `depth_emb` ← zeros ✓

The pretrained `pos_embed` warm-start is preserved in decomposed form. The network begins effectively behaving as if using its original 2D positional signal (with mild approximation), and the depth axis gradually learns from scratch without disrupting pretrained weights.

---

## 4. Optimizer Group Assignment

| Group | LR | Correct? |
|---|---|---|
| backbone (ViT, excluding depth_bucket_pe) | 1e-5 | ✓ |
| depth_bucket_pe | 1e-4 | ✓ — new module, higher LR appropriate |
| head (Pose3DHead) | 1e-4 | ✓ |

Registering `pos_embed` as a frozen buffer (not a parameter) ensures it is excluded from all optimizer groups. Correct.

---

## 5. Budget Feasibility

- New parameters: `(40 + 24 + 16) × 1024 = 81,920` floats ≈ **328 KB** — negligible.
- No extra layers, just embedding lookups and element-wise addition.
- No additional activation memory beyond baseline.
- Well within 11 GB VRAM at 20 epochs.

---

## 6. Builder Implementation Notes Completeness

All critical implementation details are present:
1. Zero `vit.pos_embed` and register as buffer — clearly specified ✓
2. Manual ViT forward (patch_embed → DepthBucketPE → layers → norm) — clearly specified ✓
3. Depth bin clamping to `[0, 15]` — explicitly noted ✓
4. `num_depth_bins = 16` as fixed constant — specified ✓
5. Module defined in `train.py` — specified ✓
6. Head unchanged — confirmed ✓

No ambiguity for the Builder.

---

## Summary

No mathematical errors, tensor shapes are fully correct, warm-start is valid, optimizer groups are properly assigned, VRAM budget is unaffected, and Builder notes are complete. 

**APPROVED for implementation.**
