# Design 002 — relative_depth_bias

## Overview

Inject depth-awareness into the **Pose3DHead cross-attention** by adding a learned depth-based additive bias to the cross-attention logits. Each joint query's attention over the 960 backbone tokens is modulated by the depth value of each corresponding patch. The bias is computed as a learned linear projection of the per-patch depth value, producing a scalar offset per query-key pair that is added before the softmax in cross-attention.

---

## Problem

The baseline `Pose3DHead` cross-attends from 70 joint queries to 960 backbone tokens using standard dot-product attention. The queries have no direct access to depth structure when computing attention scores — they must discover it implicitly through the attended features. An explicit depth-based bias in the attention logits can guide each joint query to focus on patches at the geometrically appropriate depth level.

---

## Proposed Solution

### Module: `DepthAttentionBias`

A small module that, given the depth map and patch grid size, computes an additive bias tensor of shape `(B, num_joints, N_mem)` = `(B, 70, 960)` to be added to the cross-attention logits before softmax.

#### Parameters

| Parameter | Shape | Init |
|---|---|---|
| `depth_proj` | `nn.Linear(1, num_joints)` | **Zero-initialized** (weight and bias = 0) |

Total new params: `num_joints × 1 + num_joints = 70 × 2 = 140` parameters.

The bias is shared across all attention heads (a head-agnostic depth signal).

#### Depth Bias Computation

```python
# depth_ch: (B, 1, 640, 384) — normalized depth channel from RGBD input
depth_patches = F.avg_pool2d(depth_ch, kernel_size=16, stride=16)  # (B, 1, 40, 24)
depth_flat = depth_patches.reshape(B, 1, -1).permute(0, 2, 1)      # (B, 960, 1)

# Project depth scalar to per-joint bias: (B, 960, num_joints) → transpose → (B, num_joints, 960)
bias = self.depth_proj(depth_flat)          # (B, 960, 70)
bias = bias.permute(0, 2, 1)               # (B, 70, 960)
```

The zero initialization means `bias = 0` at epoch 0, so the network starts from baseline cross-attention behavior.

#### Injection into Cross-Attention

The `Pose3DHead` normally calls:
```python
out = self.decoder(queries, memory)
```

In this design, the `TransformerDecoder` is replaced by a **manual layer loop** that intercepts the cross-attention step and adds the depth bias:

```python
# Manual decoder loop in Pose3DHead.forward
tgt = queries   # (B, 70, hidden_dim) — batch_first=True
for layer in self.decoder.layers:
    # 1. Self-attention sublayer (unchanged)
    tgt2 = layer.norm1(tgt)
    tgt2, _ = layer.self_attn(tgt2, tgt2, tgt2)
    tgt = tgt + layer.dropout1(tgt2)

    # 2. Cross-attention sublayer with depth bias injection
    tgt2 = layer.norm2(tgt)
    # Compute depth bias: (B, 70, 960)
    depth_bias = self.depth_attn_bias(depth_ch, B)   # (B, 70, 960)
    # Expand for multi-head: (B*num_heads, 70, 960)
    depth_bias_expanded = depth_bias.unsqueeze(1).expand(
        B, layer.multihead_attn.num_heads, -1, -1
    ).reshape(B * layer.multihead_attn.num_heads, tgt2.shape[1], memory.shape[1])

    # Use F.scaled_dot_product_attention or manual attn with additive mask
    # Pass as attn_mask to multihead_attn:
    tgt2, _ = layer.multihead_attn(
        tgt2, memory, memory,
        attn_mask=depth_bias_expanded   # additive mask, shape (B*nH, 70, 960)
    )
    tgt = tgt + layer.dropout2(tgt2)

    # 3. FFN sublayer (unchanged)
    tgt2 = layer.norm3(tgt)
    tgt2 = layer.linear2(layer.dropout(layer.activation(layer.linear1(tgt2))))
    tgt = tgt + layer.dropout3(tgt2)

if self.decoder.norm is not None:
    tgt = self.decoder.norm(tgt)
out = tgt
```

**Note on `nn.MultiheadAttention` with `batch_first=True`:**

The baseline constructs `TransformerDecoderLayer` with `batch_first=True`. With `batch_first=True`, `nn.MultiheadAttention` expects `attn_mask` of shape `(B*num_heads, tgt_len, src_len)` = `(B*num_heads, 70, 960)`. The depth bias computed above matches this shape exactly.

The `attn_mask` in PyTorch `nn.MultiheadAttention` is **additive** (added to the attention logits before softmax), which is exactly what we want.

---

## Architecture Changes Summary

| Component | Baseline | Design 002 |
|---|---|---|
| Cross-attention in decoder | Standard (no bias) | + additive depth bias from `DepthAttentionBias` |
| `DepthAttentionBias.depth_proj` | — | `Linear(1, 70)`, zero-init |
| Decoder forward | `self.decoder(queries, memory)` | Manual layer loop with bias injection |
| Backbone | Unchanged | Unchanged |

---

## Optimizer Groups

| Group | Parameters | LR | Weight Decay |
|---|---|---|---|
| `backbone` | All ViT params | `1e-5` | `0.03` |
| `head` | All `Pose3DHead` params + `DepthAttentionBias.depth_proj` | `1e-4` | `0.03` |

The `DepthAttentionBias` module is owned by the head (instantiated inside `Pose3DHead.__init__`), so it naturally falls into the head LR group.

---

## Memory Budget

- `depth_bias_expanded`: shape `(B*nH, 70, 960)` = `(4*8, 70, 960)` = `(32, 70, 960)` ≈ 8.4M floats ≈ 34 MB. Acceptable within 11 GB.
- Parameter addition: 140 params — negligible.

---

## Builder Implementation Notes

1. **`DepthAttentionBias` module**: Define as a standalone `nn.Module` in `train.py`. It takes `depth_ch: (B, 1, 640, 384)` and `B: int` and returns `bias: (B, num_joints, N_mem)`.

2. **Manual decoder loop**: Replace `self.decoder(queries, memory)` with a loop over `self.decoder.layers`. Use PyTorch's `nn.TransformerDecoderLayer` attribute names exactly: `norm1`, `norm2`, `norm3`, `self_attn`, `multihead_attn`, `linear1`, `linear2`, `activation`, `dropout`, `dropout1`, `dropout2`, `dropout3`. Verify attribute names against the installed PyTorch version before coding.

3. **`batch_first=True` shape**: The baseline decoder uses `batch_first=True`. Confirm `nn.MultiheadAttention` receives queries in shape `(B, 70, hidden_dim)` and `attn_mask` in shape `(B*num_heads, 70, 960)`. Test with a synthetic batch first.

4. **Pass depth to head**: The `SapiensPose3D.forward` must extract `depth_ch = x[:, 3:4, :, :]` and pass it to `self.head.forward(feat, depth_ch)`. Modify `Pose3DHead.forward` signature to accept `depth_ch` as an additional argument.

5. **`num_heads` must match**: The `num_heads` used for `depth_bias_expanded` must equal the `nhead` of `TransformerDecoderLayer` (default `head_num_heads=8` in baseline config). Hard-code `num_heads=8` or read it from `layer.multihead_attn.num_heads`.

6. **Zero init**: Initialize `depth_proj.weight` and `depth_proj.bias` to zeros in `DepthAttentionBias.__init__` using `nn.init.zeros_`.

---

## Hyperparameters (all other settings identical to baseline)

- `arch = "sapiens_0.3b"`
- `img_h = 640, img_w = 384`
- `epochs = 20`
- `lr_backbone = 1e-5`, `lr_head = 1e-4`
- `weight_decay = 0.03`
- `warmup_epochs = 3`
- `lambda_depth = 0.1`, `lambda_uv = 0.2`
- `head_num_heads = 8` (unchanged)
- `head_num_layers = 4` (unchanged)
