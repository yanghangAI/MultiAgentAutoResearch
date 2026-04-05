# Code Review: design003 — Hard Kinematic Mask

**Design ID:** design003
**Design Name:** Hard Kinematic Mask
**Reviewer:** Experiment Designer
**Review Date:** 2026-04-02
**Verdict:** APPROVED

---

## Review Checklist

### 1. Backbone Architecture

**Spec:** `SapiensBackboneRGBD` with `arch="sapiens_0.3b"` (embed_dim=1024, 24 layers), input `(640, 384)` RGBD, `drop_path_rate=0.1`.

**Implementation:** `_Cfg` sets `arch="sapiens_0.3b"`, `img_h=640`, `img_w=384`, `drop_path=0.1`. `SapiensPose3D` passes `drop_path_rate=args.drop_path` to `SapiensBackboneRGBD`.

**Result:** MATCH

---

### 2. Head Configuration

**Spec:** `in_channels=1024`, `num_joints=70`, `hidden_dim=256`, `num_heads=8`, `num_layers=4`, `dropout=0.1`, `attention_method="hard_kinematic_mask"`.

**Implementation:** `_Cfg` sets `head_hidden=256`, `head_num_heads=8`, `head_num_layers=4`, `head_dropout=0.1`. In `main()`, `SapiensPose3D` is constructed with `attention_method="hard_kinematic_mask"`. `Pose3DHead` receives `in_channels=SAPIENS_ARCHS["sapiens_0.3b"]["embed_dim"]=1024`, `num_joints=NUM_JOINTS=70`.

**Result:** MATCH

---

### 3. HOP_DIST Matrix

**Spec:** BFS on undirected `SMPLX_SKELETON` graph (remapped 0..69 indices), `fill_value=NUM_JOINTS=70` sentinel for unreachable pairs, `dtype=torch.long`, shape `(70, 70)`. Computed at module level.

**Implementation:** `_build_hop_distance_matrix(NUM_JOINTS, SMPLX_SKELETON)` is called at module level to produce `HOP_DIST`. The function initialises `dist` with `fill_value=num_joints`, `dtype=torch.long`, sets `dist[src, src]=0`, and performs BFS using `deque`. Unreachable pairs retain value 70.

**Result:** MATCH

---

### 4. Hard Mask Precomputation

**Spec (exact pseudocode):**
```python
HOP_RADIUS = 2
d = HOP_DIST  # (70, 70), dtype=torch.long
allowed = (d <= HOP_RADIUS)  # True where hop distance <= 2
fully_masked_rows = ~allowed.any(dim=1)
allowed[fully_masked_rows, :] = True
hard_mask = torch.zeros(NUM_JOINTS, NUM_JOINTS, dtype=torch.float32)
hard_mask[~allowed] = float("-inf")
self.register_buffer("hard_mask", hard_mask)  # shape (70, 70), float32
```

**Implementation (lines 519–528):**
```python
if attention_method == "hard_kinematic_mask":
    HOP_RADIUS = 2
    d = HOP_DIST  # (70, 70), dtype=torch.long
    allowed = (d <= HOP_RADIUS)  # True where hop distance <= 2
    fully_masked_rows = ~allowed.any(dim=1)
    allowed[fully_masked_rows, :] = True
    hard_mask = torch.zeros(NUM_JOINTS, NUM_JOINTS, dtype=torch.float32)
    hard_mask[~allowed] = float("-inf")
    self.register_buffer("hard_mask", hard_mask)  # shape (70, 70), float32
```

The implementation matches the spec's pseudocode verbatim, step by step.

**Result:** MATCH

---

### 5. Forward Pass — Self-Attention Integration

**Spec:** `out = self.decoder(queries, memory, tgt_mask=self.hard_mask)` for the hard mask branch. `memory_mask` left as `None`. Cross-attention unchanged.

**Implementation (lines 547–548):**
```python
elif self.attention_method == "hard_kinematic_mask":
    out = self.decoder(queries, memory, tgt_mask=self.hard_mask)
```

Only `tgt_mask` is set; `memory_mask` is not passed (defaults to None). The soft mask branch and dense branch are handled in the same `if/elif/else` chain with correct conditions.

**Result:** MATCH

---

### 6. No Warmup or Annealing for the Mask

**Spec:** Hard masking applied from epoch 0, no warmup schedule or annealing. The `tgt_mask` is always `self.hard_mask` regardless of epoch.

**Implementation:** The hard mask is precomputed in `__init__` and registered as a fixed buffer. There is no epoch-conditional logic around `tgt_mask` in `forward`. The LR warmup schedule (`get_lr_scale`) applies to the optimizer learning rate only, not to the mask.

**Result:** MATCH

---

### 7. Buffer Registration and Device Handling

**Spec:** `self.register_buffer("hard_mask", hard_mask)` ensures device transfer, checkpoint persistence, and exclusion from `model.parameters()`.

**Implementation:** Line 528: `self.register_buffer("hard_mask", hard_mask)`. This is correctly called inside `__init__`, ensuring the buffer moves with `model.to(device)`.

**Result:** MATCH

---

### 8. Mask Shape and Broadcasting

**Spec:** Shape `(70, 70)` — PyTorch's `nn.MultiheadAttention` accepts `(T, T)` and broadcasts over batch and heads. No reshaping to `[B*num_heads, T, T]` needed.

**Implementation:** `hard_mask` is created as `torch.zeros(NUM_JOINTS, NUM_JOINTS, ...)` = `(70, 70)`. No reshape before passing to `self.decoder`.

**Result:** MATCH

---

### 9. Applied at Every Decoder Layer

**Spec:** `tgt_mask` passed to `self.decoder(...)`, which internally applies it at every decoder layer (all 4 layers).

**Implementation:** `self.decoder` is `nn.TransformerDecoder` with `num_layers=4`. The `tgt_mask` is passed directly to `self.decoder(...)`, which applies it at all 4 layers internally.

**Result:** MATCH

---

### 10. Training Hyperparameters

| Parameter | Spec | Implementation | Match? |
|-----------|------|----------------|--------|
| Epochs | 20 | `epochs=20` | YES |
| Batch size | 4 (BATCH_SIZE) | `batch_size=BATCH_SIZE` | YES |
| Grad accum steps | 8 (ACCUM_STEPS) | `accum_steps=ACCUM_STEPS` | YES |
| Optimizer | AdamW | `torch.optim.AdamW` | YES |
| `lr_backbone` | 1e-5 | `lr_backbone=1e-5` | YES |
| `lr_head` | 1e-4 | `lr_head=1e-4` | YES |
| `weight_decay` | 0.03 | `weight_decay=0.03` | YES |
| Warmup epochs | 3 | `warmup_epochs=3` | YES |
| Grad clip | 1.0 | `grad_clip=1.0` | YES |
| `lambda_depth` | 0.1 | `lambda_depth=0.1` | YES |
| `lambda_uv` | 0.2 | `lambda_uv=0.2` | YES |
| AMP | False | `amp=False` | YES |

---

### 11. Optimizer Construction

**Spec:**
```python
optimizer = torch.optim.AdamW(
    [{"params": model.backbone.parameters(), "lr": 1e-5},
     {"params": model.head.parameters(),     "lr": 1e-4}],
    weight_decay=0.03,
)
```

**Implementation (lines 965–969):**
```python
optimizer = torch.optim.AdamW(
    [{"params": model.backbone.parameters(), "lr": args.lr_backbone},
     {"params": model.head.parameters(),     "lr": args.lr_head}],
    weight_decay=args.weight_decay,
)
```

With `args.lr_backbone=1e-5`, `args.lr_head=1e-4`, `args.weight_decay=0.03`, this matches exactly.

**Result:** MATCH

---

## Summary

All design specifications in `design.md` are implemented precisely in `train.py`:

- The hard binary mask precomputation logic matches the spec's pseudocode verbatim.
- `HOP_RADIUS=2`, NaN guard (`fully_masked_rows`), mask values (0.0 / -inf), buffer registration, and shape all match.
- The mask is applied via `tgt_mask` to self-attention only; cross-attention (`memory_mask`) is unchanged.
- No warmup or annealing for the mask — hard masking from epoch 0.
- All head parameters, training hyperparameters, and optimizer configuration match the spec.
- No implementation bugs found.

**VERDICT: APPROVED**
