# Design 002 — Mid-Layer Depth Fusion (mid_fusion)

## Idea Reference
`runs/idea001/idea.md` — RGB-D Modality Fusion Strategy, option `mid_fusion`.

## Problem
Early 4-channel fusion (design001) conflates depth and RGB from the very first token projection, potentially corrupting the pretrained RGB representations. An alternative is to let the ViT process RGB tokens through the first half of its layers in the original pretrained regime, then inject the depth signal at an intermediate layer. This preserves the shallow RGB feature hierarchy intact and gives the second half of the ViT the opportunity to fuse depth with already-formed semantic RGB representations.

## Proposed Solution

Process **only the 3-channel RGB image** through the standard (unchanged) patch embedding so the first 12 transformer blocks run on clean RGB tokens. After block 11 (zero-indexed, i.e., the 12th block), add a learned per-spatial-position depth bias to the token sequence. The depth bias is produced by a lightweight **depth projection network** (`DepthProjector`) that maps the raw depth map to a `(B, N_tokens, embed_dim)` additive signal, which is added to the RGB token sequence before block 12 runs.

### Why additive bias rather than concatenated depth tokens
Concatenating new tokens would change the sequence length seen by the remaining 12 blocks, requiring a resized positional embedding for the second half only. An additive projection maintains the exact token shape `(B, 960, 1024)` throughout, keeping all pretrained weight shapes compatible with no interpolation.

### Injection layer index
- Backbone: `sapiens_0.3b` — 24 ViT blocks (index 0..23).
- Injection point: **after block 11** (halfway through, before block 12 executes).
- Rationale: blocks 0–11 build mid-level RGB features; blocks 12–23 integrate depth for 3D-aware representations.

## Architecture Changes vs. Baseline

### New class: `SapiensBackboneMidFusion`
Replaces `SapiensBackboneRGBD`. This class:
1. Instantiates a standard 3-channel Sapiens ViT (`in_channels=3`).
2. Introduces a new `DepthProjector` sub-module.
3. Hooks into the ViT's block list to inject the depth signal at layer 12.

#### `DepthProjector` module
```
DepthProjector(
    patch_size : int = 16,
    embed_dim  : int = 1024,
    img_h      : int = 640,
    img_w      : int = 384,
)
```

Internal layers:
```
depth_patch_embed : Conv2d(1, embed_dim, kernel_size=16, stride=16, padding=2)
    # same padding=2 as the RGB patch embed, so spatial output is (B, 1024, 40, 24)
depth_norm        : LayerNorm(embed_dim)
```

Forward pass:
```
depth   : (B, 1, 640, 384)
  → depth_patch_embed    → (B, 1024, 40, 24)   # Conv2d feature map
  → flatten + transpose  → (B, 960, 1024)       # match token layout: N = 40×24 = 960
  → depth_norm           → (B, 960, 1024)
```

Output: depth token tensor `d` of shape `(B, 960, 1024)`, interpreted as an **additive bias**.

#### Injection mechanism
The ViT's `forward` method is re-implemented in `SapiensBackboneMidFusion` by manually iterating over blocks:

```python
# Inside SapiensBackboneMidFusion.forward(rgb, depth):
x = self.vit.patch_embed(rgb)          # (B, 960, 1024)
x = x + self.vit.pos_embed            # positional embedding (unchanged)
for i, block in enumerate(self.vit.layers):
    if i == 12:
        d = self.depth_proj(depth)     # (B, 960, 1024)
        x = x + d                     # additive depth injection
    x = block(x)                      # standard ViT block
x = self.vit.ln1(x)                   # final layer norm (Sapiens uses ln1 as final norm)
# reshape to feature map
x = x.transpose(1, 2).reshape(B, embed_dim, 40, 24)
```

### Data flow
```
rgb    : (B, 3, 640, 384)   — ImageNet normalized, fed to standard 3-ch patch embed
depth  : (B, 1, 640, 384)   — clipped [0, 10m] / 10.0, fed to DepthProjector
  → patch_embed (3-ch)      → (B, 960, 1024)
  → ViT blocks 0–11         → (B, 960, 1024)
  → + depth_proj(depth)     → (B, 960, 1024)   [additive injection]
  → ViT blocks 12–23        → (B, 960, 1024)
  → final LayerNorm         → (B, 960, 1024)
  → reshape                 → (B, 1024, 40, 24)
  → Pose3DHead              → {"joints": (B, 70, 3), "pelvis_depth": (B, 1), "pelvis_uv": (B, 2)}
```

## Initialization Strategy

### RGB ViT weights
Load from the standard 3-channel Sapiens pretrained checkpoint (`sapiens_0.3b_epoch_1600_clean.pth`) **without modification** — no channel expansion needed, patch embed weight shape is `(1024, 3, 16, 16)` as in the original.

### `DepthProjector` weights
- `depth_patch_embed` (Conv2d): initialized with **zeros** for both weight and bias.
  - Rationale: at epoch 0, the depth bias is zero everywhere, so the model starts in the same state as a pure RGB model. The depth pathway is grown from zero signal, reducing the risk of destabilizing pretrained RGB features.
- `depth_norm` (LayerNorm): standard initialization (weight=1, bias=0).

### ViT blocks
All 24 ViT blocks are **unfrozen** and fine-tuned, same as design001. Freezing blocks 0–11 was considered but rejected: it would prevent the RGB representations from adapting to the mid-fusion paradigm, and the pretrained LR (1e-5) is already conservative enough to protect early features.

## Configuration

| Parameter | Value |
|-----------|-------|
| `arch` | `sapiens_0.3b` |
| `fusion_strategy` | `mid_fusion` |
| `injection_layer` | `12` (0-indexed; after block 11, before block 12) |
| `img_h × img_w` | `640 × 384` |
| `N_tokens` | `960` (= 40 × 24) |
| `embed_dim` | `1024` |
| `depth_proj_init` | `zeros` (Conv2d weight and bias) |
| `epochs` | `20` |
| `batch_size` | `4` (from `BATCH_SIZE` constant in `infra.py`) |
| `accum_steps` | `8` (from `ACCUM_STEPS` constant in `infra.py`) |
| `lr_backbone` | `1e-5` |
| `lr_depth_proj` | `1e-4` (same group as head — new module, needs faster learning) |
| `lr_head` | `1e-4` |
| `weight_decay` | `0.03` |
| `warmup_epochs` | `3` |
| `grad_clip` | `1.0` |
| `amp` | `False` |
| `drop_path` | `0.1` |
| `head_hidden` | `256` |
| `head_num_heads` | `8` |
| `head_num_layers` | `4` |
| `head_dropout` | `0.1` |
| `lambda_depth` | `0.1` |
| `lambda_uv` | `0.2` |
| `splits_file` | `splits_rome_tracking.json` |
| `output_dir` | `runs/idea001/design002` |

### Optimizer parameter groups (3 groups)
1. **Backbone ViT** (`vit.*`): `lr=1e-5`, `weight_decay=0.03`
2. **DepthProjector** (`depth_proj.*`): `lr=1e-4`, `weight_decay=0.03`
3. **Pose3DHead** (all remaining params): `lr=1e-4`, `weight_decay=0.03`

LR schedule: linear warmup over 3 epochs then cosine decay to 0 (applied to all groups proportionally via a single scheduler using `base_lr` ratios).

## Loss
Identical to baseline and design001:
```
loss = smooth_l1(pred_joints[:, BODY_IDX], gt_joints[:, BODY_IDX], beta=0.05)
     + 0.1 * smooth_l1(pred_pelvis_depth, gt_pelvis_depth, beta=0.05)
     + 0.2 * smooth_l1(pred_pelvis_uv, gt_pelvis_uv, beta=0.05)
```

## Expected Behaviour
Because depth starts as an all-zero additive term, epoch-0 loss should be identical to a pure-RGB fine-tune. The depth pathway will grow gradually as the optimizer updates `DepthProjector` weights. The hypothesis is that blocks 12–23 will learn to integrate depth cues into 3D-aware representations without disrupting the shallow RGB features learned by blocks 0–11, potentially outperforming design001's early-fusion approach.

## Implementation Notes for Builder
- Define `DepthProjector` and `SapiensBackboneMidFusion` in a new file `runs/idea001/design002/backbone_mid.py` (or inline in `train.py`).
- In `SapiensBackboneMidFusion.__init__`, construct the ViT with `in_channels=3` (standard 3-channel).
- Load pretrained weights with the existing `weights.py` loader but **skip the 4-channel patch embed expansion step** (the standard 3-ch weights load cleanly).
- Re-implement `SapiensBackboneMidFusion.forward` to manually iterate `self.vit.layers` and inject at `i == 12`.
- The `DepthProjector.depth_patch_embed` uses `padding=2` to match the RGB patch embed convention and produce the same `(40, 24)` spatial grid.
- After `depth_patch_embed`, flatten and transpose: `x.flatten(2).transpose(1, 2)` gives `(B, 960, 1024)`.
- `self.vit.ln1` is the final layer norm in mmpretrain's `VisionTransformer` when `final_norm=True`. Confirm the attribute name from the mmpretrain source; it may be `self.vit.norm` depending on version.
- Add `depth_proj` parameter group explicitly by name filter in the optimizer setup.
- Add `fusion_strategy = "mid_fusion"` attribute to `_Cfg` for logging.
- Change `_Cfg.output_dir` to `"runs/idea001/design002"`.
- The `train` loop must pass both `rgb` and `depth` separately to the backbone: `feats = model.backbone(rgb, depth)` rather than `model.backbone(torch.cat([rgb, depth], dim=1))`.
