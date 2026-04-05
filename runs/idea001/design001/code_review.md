# Code Review — idea001 / design001 (early_4ch)

**Reviewer:** Designer  
**Date:** 2026-04-02  
**Design spec:** `runs/idea001/design001/design.md`  
**Implementation:** `runs/idea001/design001/train.py`

---

## Review Result: APPROVED

The Builder's `train.py` correctly implements every requirement from `design.md`. Detailed verification follows.

---

## Verification Checklist

### Architecture

| Design Spec | Implementation | Match? |
|-------------|---------------|--------|
| Use `SapiensBackboneRGBD` exactly as in baseline (no changes) | `SapiensBackboneRGBD` defined with `in_channels=4`, unchanged from baseline | PASS |
| `arch = sapiens_0.3b` | `arch = "sapiens_0.3b"` in `_Cfg` | PASS |
| Backbone outputs `(B, 1024, 40, 24)` | `embed_dim=1024, num_layers=24` per `SAPIENS_ARCHS["sapiens_0.3b"]` | PASS |
| `drop_path = 0.1` | `drop_path = 0.1` in `_Cfg`, passed as `drop_path_rate` | PASS |

### Patch Embedding Initialization

| Design Spec | Implementation | Match? |
|-------------|---------------|--------|
| `depth_channel_weight = pretrained_weight.mean(dim=1, keepdim=True)` | `w_rgb.mean(dim=1, keepdim=True)` → `torch.cat([w_rgb, ...], dim=1)` in `load_sapiens_pretrained` | PASS |
| 4-channel weight shape `(embed_dim, 4, patch_h, patch_w)` | Produced by `torch.cat([w_rgb, w_rgb.mean(dim=1, keepdim=True)], dim=1)` | PASS |

### Data Flow

| Design Spec | Implementation | Match? |
|-------------|---------------|--------|
| `rgb: (B, 3, 640, 384)` ImageNet normalized | `ToTensor` applies ImageNet mean/std normalization | PASS |
| `depth: (B, 1, 640, 384)` clipped `[0, 10m] / 10.0` | `np.clip(depth, 0.0, self.depth_max) / self.depth_max` in `ToTensor`; `DEPTH_MAX_METERS` from infra | PASS |
| `x = torch.cat([rgb, depth], dim=1)` → `(B, 4, 640, 384)` | `x = torch.cat([rgb, depth], dim=1)` at line 658 in training loop | PASS |

### Head Configuration

| Design Spec | Implementation | Match? |
|-------------|---------------|--------|
| `head_hidden = 256` | `head_hidden = 256` in `_Cfg` | PASS |
| `head_num_heads = 8` | `head_num_heads = 8` in `_Cfg` | PASS |
| `head_num_layers = 4` | `head_num_layers = 4` in `_Cfg` | PASS |
| `head_dropout = 0.1` | `head_dropout = 0.1` in `_Cfg` | PASS |
| Outputs: `joints (B,70,3)`, `pelvis_depth (B,1)`, `pelvis_uv (B,2)` | `joints_out`, `depth_out`, `uv_out` linears in `Pose3DHead` | PASS |

### Loss Function

| Design Spec | Implementation | Match? |
|-------------|---------------|--------|
| `smooth_l1(..., beta=0.05)` for all terms | `pose_loss` in infra.py wraps `smooth_l1_loss(pred, target, beta=0.05)` | PASS |
| `loss = pose(joints[BODY_IDX]) + 0.1*pose(pelvis_depth) + 0.2*pose(pelvis_uv)` | `loss = (l_pose + args.lambda_depth * l_dep + args.lambda_uv * l_uv)` with `lambda_depth=0.1`, `lambda_uv=0.2` | PASS |

### Optimizer

| Design Spec | Implementation | Match? |
|-------------|---------------|--------|
| AdamW, two param groups | `torch.optim.AdamW([{backbone, lr=1e-5}, {head, lr=1e-4}], weight_decay=0.03)` | PASS |
| `lr_backbone = 1e-5` | `lr_backbone = 1e-5` in `_Cfg` | PASS |
| `lr_head = 1e-4` | `lr_head = 1e-4` in `_Cfg` | PASS |
| `weight_decay = 0.03` | `weight_decay = 0.03` in `_Cfg` | PASS |

### LR Schedule

| Design Spec | Implementation | Match? |
|-------------|---------------|--------|
| Linear warmup over 3 epochs | `warmup_epochs = 3`; `get_lr_scale` returns linear ramp | PASS |
| Cosine decay to 0 after warmup | `0.5 * (1.0 + math.cos(math.pi * progress))` decays toward 0 | PASS |

### Training Configuration

| Parameter | Design Spec | Implementation | Match? |
|-----------|-------------|---------------|--------|
| `epochs` | 20 | 20 | PASS |
| `batch_size` | 4 (from BATCH_SIZE in infra.py) | `BATCH_SIZE` constant | PASS |
| `accum_steps` | 8 (from ACCUM_STEPS in infra.py) | `ACCUM_STEPS` constant | PASS |
| `grad_clip` | 1.0 | 1.0 | PASS |
| `amp` | False | False | PASS |
| `splits_file` | `splits_rome_tracking.json` | `splits_rome_tracking.json` | PASS |
| `output_dir` | `runs/idea001/design001` | `runs/idea001/design001` (absolute path) | PASS |
| `fusion_strategy` | `"early_4ch"` (label, no effect) | `fusion_strategy = "early_4ch"` in `_Cfg` | PASS |

### Implementation Notes Compliance

- `train.py` is a copy of baseline with `output_dir` updated: confirmed.
- `fusion_strategy = "early_4ch"` added to `_Cfg`: confirmed.
- No model, loss, or optimizer changes vs. baseline: confirmed.
- `SapiensBackboneRGBD` uses `in_channels=4` and mean-init for 4th channel: confirmed.

---

## Summary

All parameters, equations, and architectural requirements from `design.md` are faithfully reproduced in `train.py`. No bugs or mismatches were found. The implementation is **APPROVED**.
