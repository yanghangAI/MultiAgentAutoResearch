# Code Review: idea002 / design001

**Design ID:** design001
**Design Name:** Baseline Dense (Control)
**Reviewer:** Experiment Designer
**Review Date:** 2026-04-02
**Verdict:** APPROVED

---

## Summary

The implementation in `train.py` faithfully and precisely matches the design specification in `design.md`. All architectural parameters, optimizer settings, loss weights, LR schedule logic, and the `HOP_DIST` module-level constant are correctly implemented.

---

## Detailed Verification

### 1. `_build_hop_distance_matrix` and `HOP_DIST` (Module-Level Constant)

**Design spec** (verbatim):
```python
def _build_hop_distance_matrix(num_joints, edges):
    ...
    dist = torch.full((num_joints, num_joints), fill_value=num_joints, dtype=torch.long)
    ...
HOP_DIST = _build_hop_distance_matrix(NUM_JOINTS, SMPLX_SKELETON)
```

**Implementation (lines 66–89):** Matches the design spec exactly — same BFS logic, same `fill_value=num_joints`, same `dtype=torch.long`, same module-level definition using `NUM_JOINTS` and `SMPLX_SKELETON` imported from `infra`. Docstring comments match as well.

### 2. `Pose3DHead` Architecture

**Design spec:**
- `in_channels` = 1024 (sapiens_0.3b embed_dim)
- `num_joints` = 70 (`NUM_JOINTS`)
- `hidden_dim` = 256
- `num_heads` = 8
- `num_layers` = 4
- `dropout` = 0.1
- `attention_method` argument accepted, default `"dense"`
- `forward` passes `tgt_mask=None` to `self.decoder(queries, memory, tgt_mask=None)`

**Implementation (lines 475–531):**
- `__init__` signature: `attention_method: str = "dense"` — correct.
- `nn.TransformerDecoder` instantiated with `num_layers=4`, `nhead=8`, `d_model=256`, `dropout=0.1`, `dim_feedforward=256*4=1024` — all correct.
- `forward` method: `out = self.decoder(queries, memory, tgt_mask=None)` — correct; `tgt_mask=None` is the PyTorch default, i.e., no masking, identical to `baseline.py`.
- No kinematic graph is used inside the head for this design — correct.

### 3. `SapiensBackboneRGBD`

**Design spec:** `arch="sapiens_0.3b"`, `embed_dim=1024`, 24 layers, `drop_path_rate=0.1`, input 4-channel RGB+D, image size `(640, 384)`.

**Implementation (lines 454–470, 628–635):**
- `arch = "sapiens_0.3b"` in `_Cfg`.
- `drop_path = 0.1` in `_Cfg`, passed as `drop_path_rate`.
- `img_h=640`, `img_w=384` in `_Cfg`.
- `in_channels=4` passed to `VisionTransformer` — correct.

### 4. Training Hyperparameters

| Parameter | Design Spec | Implementation (`_Cfg`) | Match? |
|---|---|---|---|
| Epochs | 20 | `epochs = 20` | YES |
| Batch size | `BATCH_SIZE` from infra | `batch_size = BATCH_SIZE` | YES |
| Accum steps | `ACCUM_STEPS` from infra | `accum_steps = ACCUM_STEPS` | YES |
| `lr_backbone` | 1e-5 | `lr_backbone = 1e-5` | YES |
| `lr_head` | 1e-4 | `lr_head = 1e-4` | YES |
| `weight_decay` | 0.03 | `weight_decay = 0.03` | YES |
| Warmup epochs | 3 | `warmup_epochs = 3` | YES |
| Grad clip | 1.0 | `grad_clip = 1.0` | YES |
| `lambda_depth` | 0.1 | `lambda_depth = 0.1` | YES |
| `lambda_uv` | 0.2 | `lambda_uv = 0.2` | YES |
| AMP | False | `amp = False` | YES |

### 5. Optimizer Construction

**Design spec:**
```python
optimizer = torch.optim.AdamW(
    [{"params": model.backbone.parameters(), "lr": 1e-5},
     {"params": model.head.parameters(),     "lr": 1e-4}],
    weight_decay=0.03,
)
```

**Implementation (lines 939–943):** Matches exactly — two parameter groups with backbone at `lr_backbone` and head at `lr_head`, `weight_decay=args.weight_decay` (0.03).

### 6. LR Schedule

**Design spec:** Cosine decay with linear warmup over 3 epochs (same `get_lr_scale` logic as `baseline.py`).

**Implementation (lines 731–736):** `get_lr_scale` implements linear warmup for `epoch < warmup_epochs`, then cosine decay. Applied per-epoch to `initial_lr` of each parameter group — correct.

### 7. `attention_method="dense"` Passed to Model

**Implementation (lines 928–933):** `SapiensPose3D` is instantiated with `attention_method="dense"` — correct. This propagates to `Pose3DHead`.

### 8. No Issues Found

- No NaN risk introduced (tgt_mask=None is a clean pass-through).
- No kinematic graph usage in this design's forward pass.
- No regressions relative to baseline.py behavior identified.

---

## Conclusion

All components of design001 are implemented correctly and precisely. The code is clean, well-commented, and the `HOP_DIST` constant is properly defined at module level for use by Designs 2 and 3.

**APPROVED**
