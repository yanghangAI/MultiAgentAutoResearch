# Kinematic Attention Masking - Design 2

**Name**: Soft Kinematic Mask
**Status**: Revised

## Overview

This design applies a soft additive bias to the self-attention logits of the joint query decoder, penalizing attention between structurally distant joints. Joints that are close in the kinematic tree (low hop count) receive little or no penalty; joints that are far apart receive a larger negative bias. The bias is applied at every decoder layer.

---

## Model Architecture

### Backbone
Identical to Design 1: `SapiensBackboneRGBD` with `arch="sapiens_0.3b"` (embed_dim=1024, 24 layers), input (640, 384) RGBD, `drop_path_rate=0.1`.

### Head: `Pose3DHead` with `attention_method="soft_kinematic_mask"`

The `proxy_train.py` uses the same unified `Pose3DHead` class as Design 1 (with the `attention_method` argument).

For `attention_method="soft_kinematic_mask"`, the head precomputes a **soft bias matrix** during `__init__` and registers it as a non-parameter buffer. This buffer is applied as `tgt_mask` in the self-attention sub-layer of `nn.TransformerDecoder` at every decoder layer.

Head configuration (identical to `baseline.py`):
- `in_channels = 1024`
- `num_joints = 70`
- `hidden_dim = 256`
- `num_heads = 8`
- `num_layers = 4`
- `dropout = 0.1`

---

## Kinematic Graph

The hop-distance matrix `HOP_DIST` is constructed at module level in `proxy_train.py` using BFS on `SMPLX_SKELETON` from `infra.py`, as described in Design 1. All 70 active joints (remapped indices 0–69) form the graph nodes. Surface landmark joints (toes, heels, fingertips, indices 55–69 in original space, remapped accordingly) that are not connected to the kinematic chain appear as isolated nodes; their hop distance to all other joints remains the sentinel value `NUM_JOINTS` (=70).

---

## Soft Bias Precomputation

During `Pose3DHead.__init__` (when `attention_method="soft_kinematic_mask"`):

```python
# HOP_DIST: (70, 70) long tensor, computed at module level
d = HOP_DIST.float()  # (70, 70)
# Soft additive bias in log-space (added to attention logits before softmax):
# bias[i, j] = d(i, j) * log(0.5)
# This equals 0.0 at d=0 (self), log(0.5)≈-0.693 at d=1, log(0.25)≈-1.386 at d=2, etc.
LOG_HALF = math.log(0.5)  # ≈ -0.6931
soft_bias = d * LOG_HALF   # (70, 70), float32
# No cutoff — the bias is applied globally to all 70×70 pairs.
# Isolated joints (d=70) receive bias = 70 * log(0.5) ≈ -48.5, which strongly
# suppresses cross-joint attention while leaving self-attention (d=0) unaffected.
# There is no NaN risk because no entry is exactly -inf; all values are finite.
self.register_buffer("soft_bias", soft_bias)  # shape (70, 70)
```

---

## Integration into `nn.TransformerDecoder`

### Which sub-layer
The bias is applied exclusively to the **self-attention sub-layer** among joint queries. In PyTorch's `nn.TransformerDecoderLayer`, this is the `tgt_mask` argument:

```python
out = self.decoder(queries, memory, tgt_mask=self.soft_bias)
```

- `queries`: `(B, 70, hidden_dim)` — joint query tokens
- `memory`: `(B, H*W, hidden_dim)` — backbone feature tokens
- `tgt_mask`: `(70, 70)` float additive bias, broadcast over batch and heads by PyTorch

### What `tgt_mask` does in PyTorch
PyTorch's `nn.TransformerDecoder` adds `tgt_mask` directly to the raw attention logits before softmax:
```
attention_logits[b, h, i, j] += tgt_mask[i, j]
```
The `(70, 70)` float tensor broadcasts correctly over batch dimension B and head dimension num_heads without any additional reshaping.

### Applied at every decoder layer
The same `self.soft_bias` buffer is passed as `tgt_mask` to `self.decoder(...)`, which internally applies it at every decoder layer (all 4 layers). No layer-specific variation.

### Cross-attention is unchanged
The `memory_mask` argument is NOT used (left as `None`). The kinematic bias applies only to joint-to-joint self-attention, not to joint-to-image-patch cross-attention.

---

## NaN Safety

The soft bias has no `-inf` entries; all values are finite floats. The minimum value is `70 * log(0.5) ≈ -48.5` (for isolated joints). Softmax over finite values is always well-defined. No NaN guard is needed.

---

## Training Parameters

All hyperparameters are **identical to `baseline.py`**:

| Parameter | Value |
|-----------|-------|
| Epochs | 20 |
| Batch size | 4 |
| Gradient accumulation steps | 8 |
| Optimizer | AdamW |
| `lr_backbone` | 1e-5 |
| `lr_head` | 1e-4 |
| `weight_decay` | 0.03 |
| Warmup epochs | 3 |
| Grad clip | 1.0 |
| `lambda_depth` | 0.1 |
| `lambda_uv` | 0.2 |
| AMP | False |
| Hardware | 1x GPU (11 GB VRAM) |

Optimizer construction:
```python
optimizer = torch.optim.AdamW(
    [{"params": model.backbone.parameters(), "lr": 1e-5},
     {"params": model.head.parameters(),     "lr": 1e-4}],
    weight_decay=0.03,
)
```

---

## Design-Specific Hyperparameters

| Hyperparameter | Value | Rationale |
|----------------|-------|-----------|
| Decay factor per hop | 0.5 | Each additional hop halves the attention probability; log(0.5) ≈ -0.693 |
| Masking radius cutoff | None (global) | Bias applied to all 70×70 pairs; no threshold |
| Isolated joint handling | finite penalty (d=70) | Strongly suppresses but does not block; avoids NaN |
| Applied layers | All 4 decoder layers | Consistent structural constraint throughout decoding |
| Applied sub-layer | Self-attention only (`tgt_mask`) | Joint-to-joint structural reasoning |

---

## Summary of What Changes vs. baseline.py

1. `Pose3DHead.__init__` accepts `attention_method="soft_kinematic_mask"`.
2. During `__init__`, precomputes `soft_bias = HOP_DIST.float() * math.log(0.5)` (shape `(70, 70)`) and registers it as `self.soft_bias` buffer.
3. `Pose3DHead.forward` calls `self.decoder(queries, memory, tgt_mask=self.soft_bias)`.
4. All other model config, loss, data pipeline, and optimizer settings are identical to `baseline.py`.
