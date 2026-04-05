# Design 001 — Early 4-Channel Fusion (early_4ch)

## Idea Reference
`runs/idea001/idea.md` — RGB-D Modality Fusion Strategy, option `early_4ch`.

## Problem
The Sapiens backbone was pretrained on RGB images with a 3-channel patch embedding. The simplest way to incorporate depth is to concatenate depth as a 4th input channel and modify only the first patch embedding layer to accept 4-channel input. This is the current baseline approach. We reproduce it here as a controlled, well-understood starting point for the fusion strategy search.

## Proposed Solution
Keep the model architecture exactly as in `baseline.py`. The depth map is concatenated with the RGB tensor before the patch embedding (i.e., `x = torch.cat([rgb, depth], dim=1)` → shape `(B, 4, 640, 384)`). The 4th channel's patch embedding weights are initialized from the mean of the 3 RGB channel weights in the pretrained checkpoint. All ViT layers see a fully fused 4-channel representation from the very first token projection.

## Architecture Changes vs. Baseline

**No changes** are required to the model architecture. This design uses `SapiensBackboneRGBD` exactly as defined in `baseline.py`.

### Patch Embedding Initialization (unchanged from baseline)
```
pretrained_weight : (embed_dim, 3, patch_h, patch_w)  →  loaded from sapiens_0.3b checkpoint
depth_channel_weight = pretrained_weight.mean(dim=1, keepdim=True)  # (embed_dim, 1, patch_h, patch_w)
new_patch_embed_weight = cat([pretrained_weight, depth_channel_weight], dim=1)  # (embed_dim, 4, patch_h, patch_w)
```

### Data flow
```
rgb    : (B, 3, 640, 384)   — ImageNet normalized
depth  : (B, 1, 640, 384)   — clipped [0, 10m] / 10.0
x      : (B, 4, 640, 384)   — concat([rgb, depth], dim=1)
  → patch_embed             → (B, 960, 1024)   [40×24 = 960 tokens]
  → ViT (24 layers)         → (B, 1024, 40, 24)
  → Pose3DHead              → {"joints": (B, 70, 3), "pelvis_depth": (B, 1), "pelvis_uv": (B, 2)}
```

## Configuration

All hyperparameters are identical to `baseline.py`. The only required change is the `output_dir` and an explicit `fusion_strategy` label in the config for bookkeeping.

| Parameter | Value |
|-----------|-------|
| `arch` | `sapiens_0.3b` |
| `fusion_strategy` | `early_4ch` |
| `img_h × img_w` | `640 × 384` |
| `epochs` | `20` |
| `batch_size` | `4` (from `BATCH_SIZE` constant in `infra.py`) |
| `accum_steps` | `8` (from `ACCUM_STEPS` constant in `infra.py`) |
| `lr_backbone` | `1e-5` |
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
| `output_dir` | `runs/idea001/design001` |

## Loss
Identical to baseline:
```
loss = smooth_l1(pred_joints[:, BODY_IDX], gt_joints[:, BODY_IDX], beta=0.05)
     + 0.1 * smooth_l1(pred_pelvis_depth, gt_pelvis_depth, beta=0.05)
     + 0.2 * smooth_l1(pred_pelvis_uv, gt_pelvis_uv, beta=0.05)
```

## Optimizer
AdamW with two parameter groups:
- Backbone: `lr=1e-5`, `weight_decay=0.03`
- Head: `lr=1e-4`, `weight_decay=0.03`

LR schedule: linear warmup over 3 epochs then cosine decay to 0.

## Expected Behaviour
This design serves as the **controlled baseline** for the fusion strategy comparison. It is expected to produce results approximately equal to the baseline run (MPJPE ~140–180 mm range after 20 epochs), providing a fair anchor for comparing design002 and design003.

## Implementation Notes for Builder
- Copy `baseline.py` to `runs/idea001/design001/train.py`.
- Change `_Cfg.output_dir` to `"runs/idea001/design001"`.
- Add a `fusion_strategy = "early_4ch"` attribute to `_Cfg` (no functional effect, for logging).
- No model, loss, or optimizer changes are needed.
- The `SapiensBackboneRGBD` class already uses `in_channels=4` and the pretrain loader already performs the mean-init for the 4th channel.
