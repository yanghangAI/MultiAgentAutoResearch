# Design 003 — depth_conditioned_pe

## Overview

Replace the standard bicubic-interpolated 2D positional embedding with a **continuous MLP-based positional embedding** that maps `(row_norm, col_norm, depth_patch)` → a 1024-dimensional PE correction. The pretrained 2D `pos_embed` is preserved as a fixed additive base; the MLP learns a residual correction that is conditioned on the actual depth content of each patch. This gives the most expressive depth-geometric positional signal of the three designs.

---

## Problem

The baseline PE is purely spatial (row, col) and static — it does not adapt based on depth content. Design 001 discretizes depth into bins (coarse). This design provides a **continuous** depth-conditioned PE correction via a learned MLP, allowing fine-grained modulation of position encoding based on exact depth values at each patch location.

---

## Proposed Solution

### Module: `DepthConditionedPE`

A 3-layer MLP that takes normalized `(row, col, depth)` coordinates for each patch and produces a 1024-dim PE correction.

#### MLP Architecture

```
Input:  (B, N, 3)          — [row_norm ∈ [0,1], col_norm ∈ [0,1], depth_norm ∈ [0,1]]
Layer 1: Linear(3 → 128) + GELU
Layer 2: Linear(128 → 256) + GELU
Layer 3: Linear(256 → 1024)  ← output layer
Output: (B, N, 1024)        — additive PE correction
```

Where `N = H_tok × W_tok = 40 × 24 = 960`.

#### Parameters

| Layer | Weight Shape | Bias Shape |
|---|---|---|
| `fc1` | `(128, 3)` | `(128,)` |
| `fc2` | `(256, 128)` | `(256,)` |
| `fc3` | `(1024, 256)` | `(1024,)` |

Total MLP params: `3×128 + 128 + 128×256 + 256 + 256×1024 + 1024 = 384 + 128 + 32768 + 256 + 262144 + 1024 = 296,704` ≈ 296K params ≈ 1.2 MB.

#### Initialization

All layers use **Xavier uniform with gain=0.01**:

```python
for layer in [self.fc1, self.fc2, self.fc3]:
    nn.init.xavier_uniform_(layer.weight, gain=0.01)
    nn.init.zeros_(layer.bias)
```

The very small gain (0.01) ensures the MLP output is near-zero at initialization, so the network starts effectively identically to the baseline (with the pretrained `pos_embed` providing the full PE signal).

#### Input Coordinates

Row and column indices are normalized to `[0, 1]`:

```python
H_tok, W_tok = 40, 24
rows = torch.arange(H_tok, device=x.device, dtype=torch.float32) / (H_tok - 1)  # (40,)
cols = torch.arange(W_tok, device=x.device, dtype=torch.float32) / (W_tok - 1)  # (24,)
row_grid, col_grid = torch.meshgrid(rows, cols, indexing='ij')                   # (40, 24)
row_flat = row_grid.reshape(-1)   # (960,)
col_flat = col_grid.reshape(-1)   # (960,)
```

Depth per patch is obtained by average pooling the depth channel to the patch grid:

```python
depth_ch = x[:, 3:4, :, :]                                            # (B, 1, 640, 384)
depth_patches = F.avg_pool2d(depth_ch, kernel_size=16, stride=16)      # (B, 1, 40, 24)
depth_flat = depth_patches.reshape(B, -1)                              # (B, 960)  values in [0,1]
```

Assemble the 3D coordinate tensor:

```python
# Broadcast row/col across batch: (1, 960) → (B, 960)
row_batch = row_flat.unsqueeze(0).expand(B, -1)    # (B, 960)
col_batch = col_flat.unsqueeze(0).expand(B, -1)    # (B, 960)

# Stack: (B, 960, 3)
coords = torch.stack([row_batch, col_batch, depth_flat], dim=-1)   # (B, 960, 3)
```

#### Forward Pass: PE Correction

```python
pe_correction = self.depth_cond_pe(coords)  # (B, 960, 1024) — MLP output
```

#### Injection into Backbone Forward

The standard 2D `pos_embed` is kept as a registered `nn.Parameter` of shape `(1, 960, 1024)` (loaded from pretrained checkpoint via bicubic interpolation). The PE correction is added on top:

```python
# In SapiensBackboneRGBD.forward:
patch_tokens = vit.patch_embed(x)                # (B, 960, 1024)

# Standard pretrained 2D PE (kept frozen or fine-tuned at backbone LR)
pe_base = self.vit.pos_embed                     # (1, 960, 1024)

# MLP depth correction
pe_correction = self.depth_cond_pe(coords)       # (B, 960, 1024)

patch_tokens = patch_tokens + pe_base + pe_correction  # (B, 960, 1024)

# Then run through ViT transformer layers:
x_tokens = patch_tokens
for layer in self.vit.layers:
    x_tokens = layer(x_tokens)
x_tokens = self.vit.norm(x_tokens)

# Reshape back to feature map: (B, 1024, 40, 24)
feat = x_tokens.reshape(B, H_tok, W_tok, -1).permute(0, 3, 1, 2)
```

**Critical**: The ViT's own `forward` method internally adds `pos_embed`. To avoid double-adding, the `SapiensBackboneRGBD.forward` must **bypass `vit.forward()`** and manually call `patch_embed → pe addition → layers → norm`. Do not call `self.vit(x)`.

---

## Architecture Changes Summary

| Component | Baseline | Design 003 |
|---|---|---|
| `vit.pos_embed` | `(1, 960, 1024)` pretrained | Kept as-is (pretrained, trainable at backbone LR) |
| `depth_cond_pe` MLP | — | 3-layer MLP: `3→128→256→1024`, Xavier(0.01) |
| Forward injection | `vit.forward(x)` | Manual: `patch_embed → (pe_base + pe_correction) → layers → norm` |
| Backbone | Unchanged params | + MLP correction on top of PE |

---

## Optimizer Groups

| Group | Parameters | LR | Weight Decay |
|---|---|---|---|
| `backbone` | All ViT params including `vit.pos_embed` | `1e-5` | `0.03` |
| `depth_cond_pe` | MLP `fc1`, `fc2`, `fc3` weights + biases | `1e-4` | `0.03` |
| `head` | All `Pose3DHead` params | `1e-4` | `0.03` |

The `depth_cond_pe` MLP is part of `SapiensBackboneRGBD` (not the ViT), so it must be explicitly excluded from the backbone parameter group when setting up the optimizer. Use a name-based filter.

---

## Memory Budget

- MLP activations for `(B=4, N=960)`: negligible — `3840` forward passes through a 3-layer MLP of size 3→128→256→1024. Intermediate tensors: `(4, 960, 128)` + `(4, 960, 256)` + `(4, 960, 1024)` ≈ 0.5M + 1M + 4M floats ≈ 22 MB. Acceptable.
- MLP params: ~296K ≈ 1.2 MB.

---

## Builder Implementation Notes

1. **Bypass `vit.forward()`**: The Builder MUST inspect the mmpretrain `VisionTransformer` module tree with `print(model.backbone.vit)` to identify exact attribute names. Expected: `vit.patch_embed`, `vit.pos_embed`, `vit.layers` (or `vit.blocks`), `vit.norm`. Do NOT use `vit.forward()` directly as it internally adds `pos_embed`.

2. **`pos_embed` registration**: After `load_sapiens_pretrained`, confirm that `model.backbone.vit.pos_embed` is still a registered `nn.Parameter` (not a buffer). The pretrained interpolated value should be stored in it correctly.

3. **No double-add**: The manual forward must add `pos_embed` exactly once. Set a clear comment in the code: `# pos_embed added here; vit.forward() is NOT called`.

4. **`depth_cond_pe` optimizer group**: Filter with `lambda name, param: 'depth_cond_pe' in name` to build the separate LR group. All other backbone params (including `vit.pos_embed`) go into the backbone group at LR=1e-5.

5. **Input normalization**: `depth_flat` values are already in `[0, 1]` (normalized by `ToTensor`). Row and column coords are normalized to `[0, 1]` as described above. No additional normalization needed.

6. **`DepthConditionedPE` class**: Define as a standalone `nn.Module` in `train.py` with `__init__(self, embed_dim=1024)` and `forward(self, coords: Tensor) -> Tensor` where `coords: (B, N, 3) → output: (B, N, embed_dim)`.

7. **`avg_pool2d` stride**: Use `kernel_size=16, stride=16` to exactly match the ViT patch stride of 16 (with `patch_cfg=dict(padding=2)`, the effective patch resolution is 40×24 matching the ViT's `patch_resolution`). Verify `depth_patches.shape == (B, 1, 40, 24)` in a debug print.

---

## Hyperparameters (all other settings identical to baseline)

- `arch = "sapiens_0.3b"`
- `img_h = 640, img_w = 384`
- `epochs = 20`
- `lr_backbone = 1e-5`, `lr_head = 1e-4`, `lr_depth_pe = 1e-4`
- `weight_decay = 0.03`
- `warmup_epochs = 3`
- `lambda_depth = 0.1`, `lambda_uv = 0.2`
- MLP hidden dims: `[128, 256]` (fixed, not a config arg)
- MLP init gain: `0.01` (fixed)
