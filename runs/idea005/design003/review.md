# Review — Design 003 (depth_conditioned_pe)

**Reviewer:** Architect  
**Date:** 2026-04-03  
**Decision:** APPROVED

---

## Mathematical Soundness

The formulation is correct. The MLP receives `(B, N, 3)` coordinates and produces `(B, N, 1024)` corrections. Additive composition `patch_tokens + pe_base + pe_correction` is valid — pe_base `(1, 960, 1024)` broadcasts correctly over the batch dimension. The MLP's near-zero Xavier init (`gain=0.01`) guarantees `pe_correction ≈ 0` at epoch 0, so the warm-start is effectively identical to the baseline.

Depth patch alignment: `F.avg_pool2d(depth_ch, kernel_size=16, stride=16)` on `(B, 1, 640, 384)` → `(B, 1, 40, 24)` is exact (640/16=40, 384/16=24). Minor caveat: patch_embed uses `padding=2`, so ViT patches are over a padded 644×388 input, while depth is pooled without padding — a half-patch spatial offset at the image boundary. This is a minor imperfection only at border patches, not a correctness failure.

---

## Tensor Shape Verification

| Tensor | Expected Shape | Status |
|---|---|---|
| `depth_ch` | `(B, 1, 640, 384)` | ✓ |
| `depth_patches` | `(B, 1, 40, 24)` | ✓ |
| `depth_flat` | `(B, 960)` | ✓ |
| `coords` | `(B, 960, 3)` | ✓ |
| `pe_correction` | `(B, 960, 1024)` | ✓ |
| `pe_base` | `(1, 960, 1024)` → broadcasts | ✓ |
| `patch_tokens` after add | `(B, 960, 1024)` | ✓ |
| `feat` after reshape+permute | `(B, 1024, 40, 24)` | ✓ |

---

## Initialization Strategy

Xavier uniform `gain=0.01` on all three MLP layers, zero bias. This yields near-zero output, so `pe_correction ≈ 0` at init — pretrained `pos_embed` provides the full PE signal from epoch 0. Warm-start is fully preserved. No issue.

---

## Optimizer Groups

| Group | LR | Correct? |
|---|---|---|
| `backbone` (all ViT params incl. `vit.pos_embed`) | `1e-5` | ✓ |
| `depth_cond_pe` MLP (`fc1`, `fc2`, `fc3`) | `1e-4` | ✓ |
| `head` | `1e-4` | ✓ |

Name-based filter `'depth_cond_pe' in name` correctly separates the MLP from the backbone group. The `vit.pos_embed` parameter stays in the backbone group at `1e-5` as intended. All assignments are appropriate.

---

## Budget Feasibility (11 GB VRAM, 20 epochs)

- New params: ~296K ≈ 1.2 MB — negligible.
- Intermediate activations (B=4): `(4,960,128)` + `(4,960,256)` + `(4,960,1024)` ≈ 22 MB — negligible.
- 20 epochs at baseline throughput: no concern.
- **APPROVED on budget.**

---

## Builder Implementation Notes Completeness

Notes are comprehensive and unambiguous:
1. Inspect mmpretrain ViT attributes before coding override — critical, correctly flagged.
2. `pos_embed` registration check after `load_sapiens_pretrained` — important, included.
3. Explicit no-double-add comment requirement — included.
4. Name-based optimizer filter — included.
5. Input normalization confirmation — included.
6. `DepthConditionedPE` class signature — included.
7. `avg_pool2d` stride verification debug print — included.

No gaps in Builder guidance.

---

## Verdict

Design is mathematically sound, tensor shapes are correct, initialization preserves warm-start, optimizer groups are properly assigned, budget is not a concern, and Builder notes are complete. The border-patch depth misalignment (due to patch_embed padding=2 vs. no-padding depth pool) is a known minor imperfection that does not invalidate the design.

**APPROVED.**
