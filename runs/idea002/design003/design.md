# Kinematic Attention Masking - Design 3

**Name**: Hard Kinematic Mask
**Status**: Revised

## Overview

This design applies a hard binary mask to the self-attention logits of the joint query decoder. Joints within a 2-hop neighborhood in the kinematic tree (including self) are allowed to attend freely (bias = 0.0); joints outside this neighborhood are completely blocked (bias = -inf). The mask is precomputed once, registered as a buffer, and applied at every decoder layer.

---

## Model Architecture

### Backbone
Identical to Designs 1 and 2: `SapiensBackboneRGBD` with `arch="sapiens_0.3b"` (embed_dim=1024, 24 layers), input (640, 384) RGBD, `drop_path_rate=0.1`.

### Head: `Pose3DHead` with `attention_method="hard_kinematic_mask"`

The `proxy_train.py` uses the same unified `Pose3DHead` class (with the `attention_method` argument). For `attention_method="hard_kinematic_mask"`, the head precomputes a **hard binary float mask** during `__init__` and registers it as a non-parameter buffer.

Head configuration (identical to `baseline.py`):
- `in_channels = 1024`
- `num_joints = 70`
- `hidden_dim = 256`
- `num_heads = 8`
- `num_layers = 4`
- `dropout = 0.1`

---

## Kinematic Graph

The hop-distance matrix `HOP_DIST` is constructed at module level in `proxy_train.py` using BFS on `SMPLX_SKELETON` from `infra.py`, exactly as described in Design 1. All 70 active joints form the graph nodes. Surface landmark joints (toes, heels, fingertips) that are not connected to the kinematic chain remain at their sentinel hop distance of `NUM_JOINTS` (=70).

---

## Hard Mask Precomputation

During `Pose3DHead.__init__` (when `attention_method="hard_kinematic_mask"`):

```python
HOP_RADIUS = 2  # joints within 2 hops (inclusive) are allowed to attend

# HOP_DIST: (70, 70) long tensor, computed at module level
d = HOP_DIST  # (70, 70), dtype=torch.long

# Step 1: Build boolean allowed mask
allowed = (d <= HOP_RADIUS)  # True where hop distance <= 2, shape (70, 70)
# Note: diagonal (d[i,i]=0) is always <= 2, so every joint always attends to itself.

# Step 2: NaN guard for fully-masked rows
# Any row that is entirely False (all joints unreachable within 2 hops) is a
# disconnected joint. Setting its entire row to True gives it dense attention,
# preventing softmax([-inf, ..., -inf]) = NaN.
fully_masked_rows = ~allowed.any(dim=1)  # (70,) boolean
allowed[fully_masked_rows, :] = True     # restore to dense for isolated joints

# Step 3: Convert to additive float bias
# PyTorch TransformerDecoder adds tgt_mask to logits before softmax:
#   logits[b, h, i, j] += tgt_mask[i, j]
# Allowed entries: bias = 0.0 (no penalty)
# Blocked entries: bias = -inf (completely suppresses attention weight)
hard_mask = torch.zeros(NUM_JOINTS, NUM_JOINTS, dtype=torch.float32)
hard_mask[~allowed] = float("-inf")

self.register_buffer("hard_mask", hard_mask)  # shape (70, 70), dtype=float32
```

---

## Integration into `nn.TransformerDecoder`

### Which sub-layer
The hard mask targets the **self-attention sub-layer** among joint queries exclusively. In PyTorch's `nn.TransformerDecoderLayer`, this is the `tgt_mask` argument:

```python
out = self.decoder(queries, memory, tgt_mask=self.hard_mask)
```

- `queries`: `(B, 70, hidden_dim)` — joint query tokens
- `memory`: `(B, H*W, hidden_dim)` — backbone feature tokens
- `tgt_mask`: `(70, 70)` float additive bias, values 0.0 (allowed) or -inf (blocked)

### Tensor shape and broadcasting
The mask shape is `(70, 70)` (i.e., `[num_joints, num_joints]`). PyTorch's `nn.MultiheadAttention` (as used inside `nn.TransformerDecoder`) accepts `attn_mask` of shape `(T, T)` and broadcasts it over both batch size B and num_heads. No reshaping to `[B*num_heads, T, T]` is needed.

### Applied at every decoder layer
The same `self.hard_mask` buffer is passed as `tgt_mask` to `self.decoder(...)`, which internally applies it at every decoder layer (all 4 layers). No layer-specific variation.

### Registered as a buffer
`self.register_buffer("hard_mask", hard_mask)` ensures:
- The mask is moved to the correct device when `model.to(device)` is called.
- The mask is saved/loaded with model checkpoints (non-parameter state).
- It is not included in `model.parameters()` (no gradients, no optimizer updates).

### Cross-attention is unchanged
`memory_mask` is left as `None`. The kinematic mask applies only to joint-to-joint self-attention, not to joint-to-image-patch cross-attention.

---

## NaN Guard Details

With a 2-hop hard mask, joints with no neighbors within 2 hops in the `SMPLX_SKELETON` graph would produce a fully-`-inf` row and cause `softmax([-inf,...,-inf]) = NaN`.

The guard handles this as follows:
1. **Self-attention (diagonal):** `d[i,i] = 0 <= 2`, so every joint always attends to itself. A joint can only be fully masked if it has no kinematic edges at all (completely isolated node in the 70-joint graph).
2. **Isolated joints:** Surface landmark joints (e.g., toes, heels, fingertip tip joints) that appear in `ACTIVE_JOINT_INDICES` but have no edges in `SMPLX_SKELETON` would have `d[i, j] = 70` for all `j != i`. However, `d[i, i] = 0`, so the diagonal is always allowed. Therefore, in practice, no row is fully `-inf` given the diagonal rule alone. The `fully_masked_rows` check is a defensive guard for any edge case (e.g., if `d[i,i]` were to be miscoded); it sets such rows to dense attention as a fallback.

---

## Gradient Behavior

Hard `-inf` entries produce zero softmax weights, so **no gradient flows through blocked pairs**. For joints at the periphery of the kinematic tree (e.g., fingertip joint 3, which is 2 hops from the wrist via 2 intermediate joints), the 2-hop radius may be tight. This is accepted as a deliberate design choice — **hard masking from epoch 0, no warmup or annealing schedule**. The rationale is that anatomical constraints should be enforced from the start; any gradient restriction is considered a feature, not a bug. This is explicitly documented so the Builder does not add a warmup.

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
| Hop radius | 2 | Allows direct neighbors and 2nd-degree connections; balances locality and connectivity |
| Inside-radius bias | 0.0 | No penalty for structurally close joints |
| Outside-radius bias | -inf | Complete blockage of attention |
| Isolated joint handling | Dense attention (row set to all-0.0) | NaN guard for disconnected nodes |
| Warmup/annealing | None | Hard mask from epoch 0 |
| Applied layers | All 4 decoder layers | Consistent structural constraint throughout decoding |
| Applied sub-layer | Self-attention only (`tgt_mask`) | Joint-to-joint structural reasoning |

---

## Summary of What Changes vs. baseline.py

1. `Pose3DHead.__init__` accepts `attention_method="hard_kinematic_mask"`.
2. During `__init__`, precomputes `hard_mask` (shape `(70, 70)`, float32, values `0.0` within 2-hop neighborhood inclusive of self, `-inf` outside), with NaN guard for fully-isolated nodes, and registers it as `self.hard_mask` buffer.
3. `Pose3DHead.forward` calls `self.decoder(queries, memory, tgt_mask=self.hard_mask)`.
4. No warmup or annealing; hard masking is applied from epoch 0.
5. All other model config, loss, data pipeline, and optimizer settings are identical to `baseline.py`.
