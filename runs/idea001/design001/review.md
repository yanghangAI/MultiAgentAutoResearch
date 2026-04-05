# Review — Design 001 (`early_4ch`)

**Idea:** idea001 — RGB-D Modality Fusion Strategy  
**Design ID:** design001  
**Reviewer:** Architect  
**Date:** 2026-04-02  
**Verdict:** APPROVED

---

## Summary

Design 001 proposes reproducing the existing baseline exactly under the idea001 fusion-strategy comparison umbrella. No architectural changes are made. The design is straightforward and low-risk.

---

## Mathematical Correctness

- **Patch embedding 4th-channel init:** `depth_channel_weight = pretrained_weight.mean(dim=1, keepdim=True)` is mathematically valid. It initializes the depth channel weight as a neutral average of the RGB channels, which is the standard approach for 4-channel pretrain expansion.
- **Data flow shapes:** `(B, 4, 640, 384)` → `(B, 960, 1024)` → `(B, 1024, 40, 24)` → `{"joints": (B, 70, 3), "pelvis_depth": (B, 1), "pelvis_uv": (B, 2)}` — all shapes are consistent with `baseline.py`.
- **Loss function:** Matches `baseline.py` exactly — smooth L1 (β=0.05) on body joints, plus auxiliary depth and UV losses with `lambda_depth=0.1` and `lambda_uv=0.2`. No numerical risk.

---

## Implementation Fidelity

- The design correctly defers to `SapiensBackboneRGBD` as already defined in `baseline.py` — no new code required beyond config changes.
- `batch_size=4` and `accum_steps=8` correctly match the `BATCH_SIZE` and `ACCUM_STEPS` constants in `infra.py`. Effective batch size = 32, same as baseline.
- `amp=False` is correct for a 1080ti (no FP16 tensor cores).
- `lr_backbone=1e-5`, `lr_head=1e-4`, `weight_decay=0.03`, `warmup_epochs=3`, `grad_clip=1.0`, `drop_path=0.1` — all valid and match the baseline.
- The head config (`head_hidden=256`, `head_num_heads=8`, `head_num_layers=4`, `head_dropout=0.1`) matches the `Pose3DHead` instantiation in `baseline.py`.
- `splits_file=splits_rome_tracking.json` is consistent with the project's fixed data split policy.
- `output_dir=runs/idea001/design001` is correctly namespaced.

---

## Proxy Budget Assessment (20 epochs, single 1080ti, 11GB VRAM)

- This design is architecturally identical to the baseline. Since the baseline was already validated to fit in memory and complete within budget, this design poses no memory or time risk.
- No additional parameters are introduced.
- **Budget: SAFE.**

---

## Minor Notes

- The README states "Depth and UV auxiliary losses removed," but `baseline.py` (lines 600, 650–660) clearly retains `lambda_depth=0.1` and `lambda_uv=0.2`. The design correctly matches `baseline.py`, not the stale README note. No issue with the design itself — the README is simply out of date.
- Adding `fusion_strategy = "early_4ch"` to `_Cfg` as a bookkeeping attribute is a harmless and useful logging practice.

---

## Conclusion

Design 001 is a faithful, zero-risk reproduction of the baseline under the idea001 comparison framework. All hyperparameters, constants, shapes, and loss terms are correct and consistent with `baseline.py` and `infra.py`. Implementation instructions to the Builder are clear and minimal. **APPROVED.**
