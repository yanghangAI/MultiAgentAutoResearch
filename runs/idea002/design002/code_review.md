# Code Review: design002 — Soft Kinematic Mask

**Design ID:** design002
**Design Name:** Soft Kinematic Mask
**Reviewer:** Experiment Designer
**Review Date:** 2026-04-02
**Verdict:** APPROVED

---

## Checklist vs. design.md

### 1. HOP_DIST construction (module-level BFS)

**Spec:** `_build_hop_distance_matrix(num_joints, edges)` using BFS on `SMPLX_SKELETON`, `fill_value=num_joints`, `dtype=torch.long`, result shape `(70, 70)`. Sentinel value `NUM_JOINTS` (=70) for unreachable pairs.

**Implementation (lines 69–93):** Exact match. BFS initialises `dist[src, src] = 0`, uses `deque`, fills unreachable pairs with `num_joints`. Returns `torch.long` tensor of shape `(NUM_JOINTS, NUM_JOINTS)`. `HOP_DIST` is assigned at module level. Comment correctly notes isolated joints 55–69 in remapped space.

**Verdict:** PASS

---

### 2. Soft bias precomputation in `Pose3DHead.__init__`

**Spec:**
```python
LOG_HALF = math.log(0.5)   # ≈ -0.6931
soft_bias = HOP_DIST.float() * LOG_HALF   # (70, 70), float32
self.register_buffer("soft_bias", soft_bias)
```
- Only when `attention_method == "soft_kinematic_mask"`
- No cutoff; all 70×70 pairs included
- No `-inf` entries; minimum value ≈ −48.5 (d=70)

**Implementation (lines 513–516):**
```python
if attention_method == "soft_kinematic_mask":
    LOG_HALF = math.log(0.5)
    soft_bias = HOP_DIST.float() * LOG_HALF
    self.register_buffer("soft_bias", soft_bias)
```
Exact match. Formula, dtype cast, buffer registration, and conditional gating all correct.

**Verdict:** PASS

---

### 3. Head parameters

**Spec:** `in_channels=1024`, `num_joints=70`, `hidden_dim=256`, `num_heads=8`, `num_layers=4`, `dropout=0.1`, `batch_first=True`, `norm_first=True`.

**Implementation (lines 494–507):** All parameters match. `TransformerDecoderLayer` constructed with `d_model=256, nhead=8, dim_feedforward=1024, dropout=0.1, batch_first=True, norm_first=True`. `TransformerDecoder` has `num_layers=4`.

**Verdict:** PASS

---

### 4. `Pose3DHead.forward` — tgt_mask application

**Spec:**
```python
out = self.decoder(queries, memory, tgt_mask=self.soft_bias)
```
Applied to self-attention sub-layer of `nn.TransformerDecoder`. `memory_mask` left as `None`. Shape `(70, 70)` broadcasts over batch and heads.

**Implementation (lines 532–535):**
```python
if self.attention_method == "soft_kinematic_mask":
    out = self.decoder(queries, memory, tgt_mask=self.soft_bias)
else:
    out = self.decoder(queries, memory, tgt_mask=None)
```
Exact match. Cross-attention mask (`memory_mask`) is not passed (defaults to `None`). The `(70, 70)` buffer broadcasts correctly per PyTorch semantics.

**Verdict:** PASS

---

### 5. Model construction in `main()`

**Spec:** `attention_method="soft_kinematic_mask"` passed to `SapiensPose3D`.

**Implementation (line 943):**
```python
attention_method="soft_kinematic_mask",
```
Correct.

**Verdict:** PASS

---

### 6. Backbone configuration

**Spec:** `SapiensBackboneRGBD` with `arch="sapiens_0.3b"` (embed_dim=1024, 24 layers), input `(640, 384)` RGBD, `drop_path_rate=0.1`.

**Implementation:** `arch="sapiens_0.3b"` (line 639), `img_h=640, img_w=384` (lines 641–642), `drop_path=0.1` (line 646). Backbone correctly passes `img_size=(img_h, img_w)` and `drop_path_rate=drop_path`. SAPIENS_ARCHS dict confirms `embed_dim=1024` for `sapiens_0.3b`.

**Verdict:** PASS

---

### 7. Training hyperparameters

**Spec table:**

| Parameter | Required | Actual |
|-----------|----------|--------|
| epochs | 20 | 20 (line 649) |
| batch_size | 4 (BATCH_SIZE) | BATCH_SIZE (line 650) |
| accum_steps | 8 (ACCUM_STEPS) | ACCUM_STEPS (line 657) |
| optimizer | AdamW | AdamW (line 950) |
| lr_backbone | 1e-5 | 1e-5 (line 653) |
| lr_head | 1e-4 | 1e-4 (line 654) |
| weight_decay | 0.03 | 0.03 (line 655) |
| warmup_epochs | 3 | 3 (line 656) |
| grad_clip | 1.0 | 1.0 (line 657) |
| lambda_depth | 0.1 | 0.1 (line 663) |
| lambda_uv | 0.2 | 0.2 (line 664) |
| amp | False | False (line 658) |

All match exactly.

**Verdict:** PASS

---

### 8. Optimizer construction

**Spec:**
```python
optimizer = torch.optim.AdamW(
    [{"params": model.backbone.parameters(), "lr": 1e-5},
     {"params": model.head.parameters(),     "lr": 1e-4}],
    weight_decay=0.03,
)
```

**Implementation (lines 950–954):** Matches verbatim (uses `args.lr_backbone`, `args.lr_head`, `args.weight_decay` which are 1e-5, 1e-4, 0.03 respectively).

**Verdict:** PASS

---

### 9. NaN safety

**Spec:** No `-inf` entries; all values finite. Min value ≈ −48.5 (d=70 × log(0.5)). No NaN guard needed.

**Implementation:** Confirmed — `HOP_DIST.float() * math.log(0.5)` produces only finite floats. Sentinel d=70 gives 70 × (−0.6931) ≈ −48.5. No `fill_with(-inf)` or masking that would cause NaN in softmax.

**Verdict:** PASS

---

### 10. LR schedule

**Spec:** Linear warmup then cosine decay, identical to baseline.

**Implementation (lines 742–747, 972–974):** `get_lr_scale` implements linear warmup for `epoch < warmup_epochs` and cosine decay thereafter. Applied per-group via `g["lr"] = g["initial_lr"] * scale`. Exact match.

**Verdict:** PASS

---

## Overall Assessment

The implementation precisely matches every aspect of the design spec:
- Soft bias formula (`d * log(0.5)`)
- Buffer registration (`self.soft_bias`, shape 70×70)
- Application via `tgt_mask` in `self.decoder(queries, memory, tgt_mask=self.soft_bias)`
- Self-attention only (no `memory_mask`)
- All 4 decoder layers (single buffer passed to top-level decoder)
- All training hyperparameters identical to baseline
- No NaN risk, no implementation bugs found

**VERDICT: APPROVED**
