# Kinematic Attention Masking - Design 1

**Name**: Baseline Dense (Control)
**Status**: Revised

## Overview

This is the unconstrained dense-attention control run. It uses the exact same `Pose3DHead` architecture as `baseline.py` with no kinematic masking applied. It establishes a reference MPJPE to compare against Designs 2 and 3.

---

## Model Architecture

### Backbone
- `SapiensBackboneRGBD` with `arch="sapiens_0.3b"` (embed_dim=1024, 24 layers)
- Input: 4-channel RGB+D, image size (640, 384)
- `drop_path_rate=0.1`

### Head: `Pose3DHead` with `attention_method` argument

The `proxy_train.py` script introduces a unified `Pose3DHead` class that accepts an `attention_method: str` argument (one of `"dense"`, `"soft_kinematic_mask"`, `"hard_kinematic_mask"`). This is the **only** structural change relative to `baseline.py`. The underlying `nn.TransformerDecoder` and all other components remain identical.

For Design 1 (`attention_method="dense"`):

- The `forward` method calls `self.decoder(queries, memory, tgt_mask=None)`.
- Passing `tgt_mask=None` to `nn.TransformerDecoder` is the PyTorch default behavior: no mask is applied to the self-attention sub-layer. This is identical in numerical behavior to `baseline.py`.
- No kinematic graph is constructed or used.

Head configuration (identical to `baseline.py`):
- `in_channels`: output channels of `sapiens_0.3b` backbone = 1024
- `num_joints = 70` (from `infra.py`: `NUM_JOINTS`)
- `hidden_dim = 256`
- `num_heads = 8`
- `num_layers = 4`
- `dropout = 0.1`

---

## Kinematic Graph (Shared Module-Level Constant)

Even though Design 1 does not use the kinematic graph, `proxy_train.py` defines the hop-distance matrix as a **shared module-level constant** so that Designs 2 and 3 can import it from the same file. The Builder must include the following at module level in `proxy_train.py`:

```python
from infra import SMPLX_SKELETON, NUM_JOINTS
import torch
from collections import deque

def _build_hop_distance_matrix(num_joints, edges):
    """BFS hop distances on the undirected graph defined by SMPLX_SKELETON."""
    # edges: tuple of (i, j) pairs already in remapped 0..69 space
    adj = [[] for _ in range(num_joints)]
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    dist = torch.full((num_joints, num_joints), fill_value=num_joints, dtype=torch.long)
    for src in range(num_joints):
        dist[src, src] = 0
        q = deque([src])
        while q:
            u = q.popleft()
            for v in adj[u]:
                if dist[src, v] == num_joints:
                    dist[src, v] = dist[src, u] + 1
                    q.append(v)
    return dist  # shape (70, 70), dtype=torch.long

HOP_DIST = _build_hop_distance_matrix(NUM_JOINTS, SMPLX_SKELETON)
# HOP_DIST[i, j] = shortest-path hop count in SMPLX_SKELETON undirected graph.
# Unreachable pairs retain value NUM_JOINTS (=70), serving as a large-but-finite sentinel.
# SMPLX_SKELETON covers only the kinematic chain joints (not face/surface landmarks),
# so joints 55-69 in the remapped space (toes, heels, fingertips) are leaves or isolated.
```

`HOP_DIST` is used by Designs 2 and 3 but is defined at module level so it is computed once at import time and shared.

---

## Training Parameters

All hyperparameters are **identical to `baseline.py`**:

| Parameter | Value | Source |
|-----------|-------|--------|
| Epochs | 20 | `baseline.py` default |
| Batch size | 4 | `infra.py: BATCH_SIZE` |
| Gradient accumulation steps | 8 | `infra.py: ACCUM_STEPS` |
| Optimizer | AdamW | `baseline.py` |
| `lr_backbone` | 1e-5 | `baseline.py` |
| `lr_head` | 1e-4 | `baseline.py` |
| `weight_decay` | 0.03 | `baseline.py` |
| Warmup epochs | 3 | `baseline.py` |
| Grad clip | 1.0 | `baseline.py` |
| `lambda_depth` | 0.1 | `baseline.py` |
| `lambda_uv` | 0.2 | `baseline.py` |
| AMP | False | `baseline.py` (no FP16 tensor cores on target GPU) |
| Hardware | 1x GPU (11 GB VRAM) | proxy budget |

Optimizer construction:
```python
optimizer = torch.optim.AdamW(
    [{"params": model.backbone.parameters(), "lr": 1e-5},
     {"params": model.head.parameters(),     "lr": 1e-4}],
    weight_decay=0.03,
)
```

LR schedule: cosine decay with linear warmup over 3 epochs (same `get_lr_scale` logic as `baseline.py`).

---

## Summary of What Changes vs. baseline.py

1. `Pose3DHead.__init__` accepts `attention_method: str` (default `"dense"`); for this design it is `"dense"`.
2. `Pose3DHead.forward` passes `tgt_mask=None` explicitly to `self.decoder(queries, memory, tgt_mask=None)`.
3. `proxy_train.py` defines `HOP_DIST` at module level (used by other designs, not this one).
4. All other model config, loss, data pipeline, and optimizer settings are identical to `baseline.py`.
