# Design 001 — discretized_depth_pe

## Overview

Replace the standard 2D positional embedding in the Sapiens ViT backbone with a **decomposed row + column + depth bucket** positional embedding. Instead of a single 2D learned PE interpolated from 64×64 → 40×24, each patch receives a sum of three separate learnable embeddings: one encoding its row position, one encoding its column position, and one encoding its discretized depth bucket. This provides explicit depth-geometric signal at the patch level before any ViT self-attention.

---

## Problem

The baseline positional embedding encodes only spatial (row, col) position. The depth channel is available as the 4th input channel, but its geometric structure (e.g., which patches correspond to near vs. far regions) is not explicitly encoded in the positional signal. The ViT must learn to extract this from activations alone. Providing a direct depth-position signal may improve the model's ability to localize joints in 3D.

---

## Proposed Solution

### Module: `DepthBucketPE`

Located in the modified `SapiensBackboneRGBD`. Replaces the backbone's `vit.pos_embed` with a decomposed sum.

#### Parameters

| Parameter | Shape | Init |
|---|---|---|
| `row_emb` | `(H_tok, embed_dim)` = `(40, 1024)` | From pretrained `pos_embed` (row-mean of 40×24 interpolated grid) |
| `col_emb` | `(W_tok, embed_dim)` = `(24, 1024)` | From pretrained `pos_embed` (col-mean of 40×24 interpolated grid) |
| `depth_emb` | `(num_depth_bins, embed_dim)` = `(16, 1024)` | **Zero-initialized** |

All three are `nn.Parameter`.

Total new params: `(40 + 24 + 16) × 1024 = 81,920` floats ≈ 328 KB.

#### Depth Discretization

The depth input (channel index 3 of the RGBD input) is normalized to `[0, 1]` (already done by `ToTensor`: `depth = clip(depth, 0, DEPTH_MAX_METERS) / DEPTH_MAX_METERS`).

Depth per patch is computed via average pooling to the patch grid:

```
depth_patches = F.avg_pool2d(depth_ch, kernel_size=16, stride=16)  # (B, 1, 40, 24)
depth_patches = depth_patches.squeeze(1)                            # (B, 40, 24)
```

Discretized into `num_depth_bins = 16` bins (uniform):

```
depth_bins = (depth_patches * num_depth_bins).long()
depth_bins = depth_bins.clamp(0, num_depth_bins - 1)               # (B, 40, 24)
```

#### Forward Pass Injection

The `DepthBucketPE` module is called **after** the patch embedding projection, in place of the ViT's standard `pos_embed` addition.

The ViT's internal `pos_embed` is zeroed out and frozen (registered as a buffer of zeros, not a parameter), so only the decomposed PE contributes:

```python
# In SapiensBackboneRGBD.forward, before feeding tokens to ViT layers:
B, N, D = patch_tokens.shape          # N = H_tok * W_tok = 960
H_tok, W_tok = 40, 24

# Build row/col position indices
rows = torch.arange(H_tok, device=x.device).unsqueeze(1).expand(H_tok, W_tok).reshape(-1)  # (960,)
cols = torch.arange(W_tok, device=x.device).unsqueeze(0).expand(H_tok, W_tok).reshape(-1)  # (960,)

# Depth bucket indices per patch
depth_ch = x[:, 3:4, :, :]                                      # (B, 1, 640, 384)
depth_patches = F.avg_pool2d(depth_ch, kernel_size=16, stride=16)  # (B, 1, 40, 24)
depth_bins = (depth_patches.squeeze(1) * 16).long().clamp(0, 15)   # (B, 40, 24)
depth_bins_flat = depth_bins.reshape(B, -1)                         # (B, 960)

# Compose PE: (1, N, D) + (1, N, D) + (B, N, D)
pe = self.depth_bucket_pe.row_emb[rows].unsqueeze(0) \
   + self.depth_bucket_pe.col_emb[cols].unsqueeze(0) \
   + self.depth_bucket_pe.depth_emb[depth_bins_flat]               # (B, 960, 1024)

patch_tokens = patch_tokens + pe
```

Then feed `patch_tokens` through the remaining ViT transformer blocks.

#### Initialization from Pretrained Weights

After loading the Sapiens pretrained checkpoint (which populates the standard 2D `pos_embed` of shape `(1, 960, 1024)` after bicubic interpolation from 64×64), extract row/col embeddings as:

```python
# pe_2d: (1, 960, 1024) → (40, 24, 1024)
pe_2d = pretrained_pos_embed.squeeze(0).reshape(40, 24, 1024)
self.depth_bucket_pe.row_emb.data.copy_(pe_2d.mean(dim=1))  # mean over cols → (40, 1024)
self.depth_bucket_pe.col_emb.data.copy_(pe_2d.mean(dim=0))  # mean over rows → (24, 1024)
# depth_emb stays zero
```

This ensures the network starts from its pretrained behavior at epoch 0 (depth term = 0, row+col ≈ original 2D PE).

---

## Architecture Changes Summary

| Component | Baseline | Design 001 |
|---|---|---|
| `vit.pos_embed` | `(1, 960, 1024)` trainable parameter | Zeroed buffer (frozen) |
| `depth_bucket_pe.row_emb` | — | `(40, 1024)` trainable, init from pretrained |
| `depth_bucket_pe.col_emb` | — | `(24, 1024)` trainable, init from pretrained |
| `depth_bucket_pe.depth_emb` | — | `(16, 1024)` trainable, zero-init |
| Forward injection point | After patch embed in ViT | Same, but uses `DepthBucketPE` output |

---

## Optimizer Groups

| Group | Parameters | LR | Weight Decay |
|---|---|---|---|
| `backbone` | All ViT params except `depth_bucket_pe` | `1e-5` | `0.03` |
| `depth_bucket_pe` | `row_emb`, `col_emb`, `depth_emb` | `1e-4` | `0.03` |
| `head` | All `Pose3DHead` params | `1e-4` | `0.03` |

The `depth_bucket_pe` parameters must be placed in the head/new-module group (LR=1e-4), NOT the backbone group.

---

## Builder Implementation Notes

1. **Zero out `vit.pos_embed`**: After loading pretrained weights, replace `model.backbone.vit.pos_embed` with a frozen buffer of zeros. Use `del model.backbone.vit.pos_embed` + `model.backbone.vit.register_buffer('pos_embed', torch.zeros(...))` to prevent it from appearing as a trainable parameter in the backbone optimizer group.

2. **Hook into ViT forward**: The `SapiensBackboneRGBD.forward` must manually call `vit.patch_embed`, then add the `DepthBucketPE` output, then run through `vit.layers` and `vit.norm`. Do not call `vit.forward(x)` directly (it will add the zeroed `pos_embed` correctly, but the custom PE must be added before the layers).

3. **Clamp depth bins**: Always clamp to `[0, num_depth_bins - 1]` before the `depth_emb` lookup to prevent index-out-of-bounds when `depth_patches` = 1.0 exactly.

4. **num_depth_bins = 16**: Fixed constant. Do not make it a config arg (keep it simple for the proxy run).

5. **Import**: `DepthBucketPE` should be defined as a standalone `nn.Module` inside `train.py`.

6. **No change to head**: `Pose3DHead` is unchanged.

---

## Hyperparameters (all other settings identical to baseline)

- `arch = "sapiens_0.3b"`
- `img_h = 640, img_w = 384`
- `epochs = 20`
- `lr_backbone = 1e-5`, `lr_head = 1e-4`, `lr_depth_pe = 1e-4`
- `weight_decay = 0.03`
- `warmup_epochs = 3`
- `lambda_depth = 0.1`, `lambda_uv = 0.2`
- `num_depth_bins = 16`
