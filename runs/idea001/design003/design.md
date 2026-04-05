# Design 003 — Late Cross-Attention Depth Fusion (late_cross_attention)

## Idea Reference
`runs/idea001/idea.md` — RGB-D Modality Fusion Strategy, option `late_cross_attention`.

## Problem
Both design001 (early_4ch) and design002 (mid_fusion) inject depth into the ViT backbone, either at the very first token projection or partway through the 24 layers. This means depth information must be processed alongside (or after) the ViT's hierarchical feature extraction, which was pretrained on RGB only. A complementary hypothesis is that the ViT backbone should be left entirely untouched — processing only RGB — and depth should be introduced as a separate modality in a dedicated cross-attention step that sits between the ViT and the Pose3DHead. This keeps the pretrained RGB feature extractor maximally intact and delegates depth integration to a small, trainable adapter module.

## Proposed Solution

Run the full 24-block Sapiens ViT on RGB only (3-channel input, no modification). After the ViT produces its spatial feature map `(B, 1024, 40, 24)`, flatten it to a token sequence `(B, 960, 1024)`. In parallel, encode the raw depth map through a lightweight **DepthTokenizer** to produce a depth token sequence of the same spatial resolution: `(B, 960, 64)`. A single-layer **DepthCrossAttention** transformer block then refines the RGB token sequence using the depth tokens: the RGB tokens act as **queries**, the depth tokens act as **keys and values**. The resulting updated RGB token sequence is reshaped back to `(B, 1024, 40, 24)` and passed to the existing `Pose3DHead` unchanged.

### Design rationale: queries/keys/values assignment

RGB tokens are queries, depth tokens are keys and values. This means each RGB spatial position asks: "what depth information is relevant here?" and gathers depth context. The alternative — depth as queries, RGB as keys/values — would discard the RGB feature vector as the primary representation, which is undesirable since the pretrained ViT produces rich semantics in the RGB tokens. Making RGB the query preserves the RGB feature as the carrier while depth modulates it.

### Why a separate depth embed dimension (64)

A 1024-dim depth encoder would match the RGB embed dimension without projection, but would be over-parameterized for a single-channel input at this stage. Using `depth_embed_dim = 64` gives a compact depth representation that is projected up to `qk_dim = 256` for the attention computation, keeping the adapter small (~3M params) relative to the backbone (~300M).

## Architecture Changes vs. Baseline

### New classes

#### `DepthTokenizer`

Encodes `(B, 1, 640, 384)` depth to `(B, 960, 64)` using a patch-aligned Conv2d followed by LayerNorm.

```
DepthTokenizer(
    depth_embed_dim : int = 64,
    patch_size      : int = 16,
    img_h           : int = 640,
    img_w           : int = 384,
    padding         : int = 2,
)
```

Internal layers:
```
depth_patch_embed : Conv2d(1, 64, kernel_size=16, stride=16, padding=2)
    # padding=2 matches the RGB patch embed convention → output spatial: (B, 64, 40, 24)
depth_norm        : LayerNorm(64)
```

Forward pass:
```
depth : (B, 1, 640, 384)
  → depth_patch_embed   → (B, 64, 40, 24)   # Conv2d, padding=2
  → flatten + transpose → (B, 960, 64)       # flatten(2).transpose(1,2); N = 40×24 = 960
  → depth_norm          → (B, 960, 64)
```

Output: depth token tensor `d` of shape `(B, 960, 64)`.

#### `DepthCrossAttention`

A single transformer decoder-style block where RGB tokens attend to depth tokens.

```
DepthCrossAttention(
    rgb_dim        : int = 1024,   # dimension of RGB (query) tokens
    depth_dim      : int = 64,     # dimension of depth (key/value) tokens
    qk_dim         : int = 256,    # projected dimension for Q, K, V
    num_heads      : int = 8,      # attention heads; head_dim = qk_dim / num_heads = 32
    dropout        : float = 0.1,
)
```

Internal layers:
```
q_proj   : Linear(1024, 256, bias=True)   # project RGB tokens to queries
k_proj   : Linear(64,   256, bias=True)   # project depth tokens to keys
v_proj   : Linear(64,   256, bias=True)   # project depth tokens to values
out_proj : Linear(256, 1024, bias=True)   # project attended output back to RGB dim
attn_drop : Dropout(0.1)
norm_q   : LayerNorm(1024)                # pre-norm on query (RGB) tokens
norm_d   : LayerNorm(64)                  # pre-norm on depth tokens
ffn_norm : LayerNorm(1024)                # pre-norm before FFN
ffn      : Sequential(
               Linear(1024, 4096),        # 4× expansion
               GELU(),
               Dropout(0.1),
               Linear(4096, 1024),
               Dropout(0.1),
           )
```

Forward pass (pre-norm + residual, standard transformer style):

```python
# x: (B, 960, 1024)  — RGB tokens (queries)
# d: (B, 960, 64)    — depth tokens (keys and values)

# --- Cross-attention sub-layer ---
xn = self.norm_q(x)          # (B, 960, 1024)   pre-norm queries
dn = self.norm_d(d)           # (B, 960, 64)     pre-norm depth
Q  = self.q_proj(xn)          # (B, 960, 256)
K  = self.k_proj(dn)          # (B, 960, 256)
V  = self.v_proj(dn)          # (B, 960, 256)

# Reshape to multi-head: (B, num_heads, N, head_dim) = (B, 8, 960, 32)
Q = Q.view(B, 960, 8, 32).transpose(1, 2)   # (B, 8, 960, 32)
K = K.view(B, 960, 8, 32).transpose(1, 2)   # (B, 8, 960, 32)
V = V.view(B, 960, 8, 32).transpose(1, 2)   # (B, 8, 960, 32)

# Scaled dot-product attention
scale = 32 ** -0.5            # head_dim = 32
attn  = (Q @ K.transpose(-2, -1)) * scale   # (B, 8, 960, 960)
attn  = attn.softmax(dim=-1)                 # (B, 8, 960, 960)
attn  = self.attn_drop(attn)                 # dropout
ctx   = (attn @ V)                           # (B, 8, 960, 32)
ctx   = ctx.transpose(1, 2).reshape(B, 960, 256)   # (B, 960, 256)
ctx   = self.out_proj(ctx)                   # (B, 960, 1024)

x = x + ctx                  # residual connection

# --- FFN sub-layer ---
x = x + self.ffn(self.ffn_norm(x))          # pre-norm + residual

return x                      # (B, 960, 1024)
```

Note: `torch.nn.functional.scaled_dot_product_attention` (PyTorch 2.0+) may be used in place of the manual QKV computation above for efficiency; behavior is identical.

#### `SapiensBackboneLateFusion`

Wraps the standard 3-channel Sapiens ViT. The backbone itself is unchanged; this class only handles the depth tokenizer and cross-attention module.

```python
class SapiensBackboneLateFusion(nn.Module):
    def __init__(self, vit, depth_tokenizer, depth_cross_attn):
        super().__init__()
        self.vit = vit                             # standard 3-ch Sapiens ViT
        self.depth_tokenizer = depth_tokenizer     # DepthTokenizer
        self.depth_cross_attn = depth_cross_attn   # DepthCrossAttention

    def forward(self, rgb, depth):
        # rgb:   (B, 3, 640, 384)
        # depth: (B, 1, 640, 384)

        # 1. Run full ViT on RGB only
        feat = self.vit(rgb)          # (B, 1024, 40, 24)  [feature map]

        # 2. Flatten feature map to token sequence
        B, C, H, W = feat.shape      # B, 1024, 40, 24
        x = feat.flatten(2).transpose(1, 2)    # (B, 960, 1024)

        # 3. Encode depth to token sequence
        d = self.depth_tokenizer(depth)         # (B, 960, 64)

        # 4. Cross-attention: RGB tokens attend to depth tokens
        x = self.depth_cross_attn(x, d)         # (B, 960, 1024)

        # 5. Reshape back to feature map for Pose3DHead
        x = x.transpose(1, 2).reshape(B, C, H, W)   # (B, 1024, 40, 24)

        return x
```

### Data flow

```
rgb    : (B, 3, 640, 384)   — ImageNet normalized, fed to standard 3-ch ViT
depth  : (B, 1, 640, 384)   — clipped [0, 10m] / 10.0
  → ViT (24 blocks, 3-ch)   → (B, 1024, 40, 24)    # full RGB ViT, unmodified
  → flatten + transpose      → (B, 960, 1024)        # RGB token sequence (queries)
  → DepthTokenizer(depth)    → (B, 960, 64)          # depth token sequence (keys + values)
  → DepthCrossAttention      → (B, 960, 1024)        # depth-modulated RGB tokens
  → transpose + reshape      → (B, 1024, 40, 24)     # back to feature map
  → Pose3DHead               → {"joints": (B, 70, 3), "pelvis_depth": (B, 1), "pelvis_uv": (B, 2)}
```

### Tensor shape summary

| Tensor | Shape | Notes |
|--------|-------|-------|
| `rgb` input | `(B, 3, 640, 384)` | standard 3-ch |
| `depth` input | `(B, 1, 640, 384)` | normalized to [0, 1] |
| ViT feature map | `(B, 1024, 40, 24)` | standard backbone output |
| RGB token sequence | `(B, 960, 1024)` | queries; N = 40×24 = 960 |
| depth token sequence | `(B, 960, 64)` | keys + values; same N |
| Q matrix | `(B, 8, 960, 32)` | after q_proj + reshape |
| K matrix | `(B, 8, 960, 32)` | after k_proj + reshape |
| V matrix | `(B, 8, 960, 32)` | after v_proj + reshape |
| attention weights | `(B, 8, 960, 960)` | softmax over 960 depth positions |
| attended output | `(B, 960, 1024)` | after out_proj + residual |
| cross-attn output | `(B, 1024, 40, 24)` | reshaped back for head |

## Initialization Strategy

### RGB ViT weights
Load from the standard 3-channel Sapiens pretrained checkpoint (`sapiens_0.3b_epoch_1600_clean.pth`) without modification — no channel expansion, no shape change. The weights load cleanly because the ViT processes only RGB.

### `DepthTokenizer` weights
- `depth_patch_embed` (Conv2d): initialized with **zeros** for both weight and bias.
  - Rationale: at epoch 0, depth tokens are all-zero, so the cross-attention output (`V = 0`) contributes zero to the residual. The model starts as a pure-RGB forward pass, with depth integration grown from a silent initialization. This minimizes disruption to the pretrained RGB representation.
- `depth_norm` (LayerNorm): standard initialization (weight=1, bias=0).

### `DepthCrossAttention` weights
- `q_proj`, `k_proj`, `v_proj`: Xavier uniform initialization (`nn.init.xavier_uniform_`). This is the standard transformer attention initialization and ensures well-scaled gradients from the start.
- `out_proj`: initialized with **zeros** for both weight and bias.
  - Rationale: combined with zero-init of `DepthTokenizer`, this gives a true identity initialization — even if the depth tokenizer were non-zero, `out_proj` zeros ensure the cross-attention residual adds zero at epoch 0. This provides a second line of defense for a clean warm-start.
- `ffn` (both Linear layers): Xavier uniform initialization.
- `norm_q`, `norm_d`, `ffn_norm` (LayerNorm): standard (weight=1, bias=0).

### Summary of zero-init chain
At epoch 0: `DepthTokenizer.depth_patch_embed` (zeros) → `d = 0` → `K = k_proj(0) = 0`, `V = v_proj(0) = 0` → `ctx = 0` → `out_proj(0) = 0` (doubly ensured by zero `out_proj`). The RGB token sequence `x` passes through the cross-attention block completely unchanged, and the FFN sub-layer is the only non-trivial computation. However, since `out_proj = 0`, even if `V` were non-zero, the cross-attention residual is zero. This makes epoch-0 behavior identical to a pure-RGB model.

## Configuration

| Parameter | Value |
|-----------|-------|
| `arch` | `sapiens_0.3b` |
| `fusion_strategy` | `late_cross_attention` |
| `img_h × img_w` | `640 × 384` |
| `N_tokens` | `960` (= 40 × 24) |
| `embed_dim` | `1024` |
| `depth_embed_dim` | `64` |
| `qk_dim` | `256` |
| `num_heads` | `8` |
| `head_dim` | `32` (= 256 / 8) |
| `ffn_expansion` | `4` (4096 hidden units in FFN) |
| `attn_dropout` | `0.1` |
| `ffn_dropout` | `0.1` |
| `depth_tokenizer_init` | `zeros` (Conv2d weight and bias) |
| `out_proj_init` | `zeros` (weight and bias) |
| `q_proj / k_proj / v_proj / ffn_init` | `xavier_uniform` |
| `epochs` | `20` |
| `batch_size` | `4` (from `BATCH_SIZE` constant in `infra.py`) |
| `accum_steps` | `8` (from `ACCUM_STEPS` constant in `infra.py`) |
| `lr_backbone` | `1e-5` |
| `lr_depth_adapter` | `1e-4` |
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
| `output_dir` | `runs/idea001/design003` |

### Optimizer parameter groups (3 groups)

1. **Backbone ViT** (`vit.*`): `lr=1e-5`, `weight_decay=0.03`
   - All 24 blocks unfrozen. The conservative LR protects pretrained RGB features while still allowing fine-tuning.
2. **Depth adapter** (`depth_tokenizer.*` + `depth_cross_attn.*`): `lr=1e-4`, `weight_decay=0.03`
   - New modules; faster LR allows them to grow from zero initialization.
3. **Pose3DHead** (remaining params): `lr=1e-4`, `weight_decay=0.03`

LR schedule: linear warmup over 3 epochs then cosine decay to 0, applied to all groups proportionally (a single scheduler with `base_lr` ratios preserved).

## Loss

Identical to baseline, design001, and design002:
```
loss = smooth_l1(pred_joints[:, BODY_IDX], gt_joints[:, BODY_IDX], beta=0.05)
     + 0.1 * smooth_l1(pred_pelvis_depth, gt_pelvis_depth, beta=0.05)
     + 0.2 * smooth_l1(pred_pelvis_uv, gt_pelvis_uv, beta=0.05)
```

## Parameter Count Estimate

| Module | Params |
|--------|--------|
| Sapiens ViT backbone (unchanged) | ~307M |
| `DepthTokenizer.depth_patch_embed` | 1×64×16×16 + 64 = 16,448 |
| `DepthTokenizer.depth_norm` | 128 |
| `DepthCrossAttention.q_proj` | 1024×256 + 256 = 262,400 |
| `DepthCrossAttention.k_proj` | 64×256 + 256 = 16,640 |
| `DepthCrossAttention.v_proj` | 64×256 + 256 = 16,640 |
| `DepthCrossAttention.out_proj` | 256×1024 + 1024 = 263,168 |
| `DepthCrossAttention.norms (×3)` | 3 × (1024+1024 or 64+64) ≈ 6,272 |
| `DepthCrossAttention.ffn` | 1024×4096 + 4096×1024 + biases ≈ 8,396,800 |
| **Depth adapter total** | **~9.0M** |
| `Pose3DHead` | ~1M (unchanged) |
| **Grand total** | **~317M** |

The depth adapter adds ~3% parameters on top of the backbone.

## Expected Behaviour

Because of the dual zero-init (DepthTokenizer Conv2d and out_proj), epoch-0 loss is identical to a pure-RGB baseline. The depth adapter must grow from zero signal. The hypothesis is that this design gives the ViT backbone the cleanest possible pretrained RGB features (since it runs entirely on 3-channel input with unchanged weights), and the cross-attention adapter has sufficient capacity (9M params, 8-head attention over 960 tokens) to learn meaningful depth-to-pose correlations. This design may outperform design002 because the full 24 ViT blocks see pure RGB, whereas design002 injects depth at block 12 and the remaining 12 blocks must adapt to the mixed representation.

## Implementation Notes for Builder

- Define `DepthTokenizer`, `DepthCrossAttention`, and `SapiensBackboneLateFusion` in a new file `runs/idea001/design003/backbone_late.py` (or inline in `train.py`).
- In `SapiensBackboneLateFusion.__init__`, instantiate the ViT with `in_channels=3`. Load pretrained weights with the existing `weights.py` loader, **skipping the 4-channel patch embed expansion** (standard 3-ch weights load cleanly).
- For the `out_proj` zero-init:
  ```python
  nn.init.zeros_(self.out_proj.weight)
  nn.init.zeros_(self.out_proj.bias)
  ```
- The `attention weights` tensor `(B, 8, 960, 960)` is 960² × 8 × B × 4 bytes = ~28MB at B=4. This is acceptable given the available GPU memory.
- `torch.nn.functional.scaled_dot_product_attention` (PyTorch ≥ 2.0) can replace the manual QKV loop for FlashAttention compatibility:
  ```python
  ctx = F.scaled_dot_product_attention(Q, K, V, dropout_p=self.dropout_p if self.training else 0.0)
  ```
  If used, set `scale=32**-0.5` via the `scale` kwarg (PyTorch ≥ 2.1) or pre-scale Q manually.
- The `train` loop must pass `rgb` and `depth` separately to the backbone: `feats = model.backbone(rgb, depth)` (same as design002 convention).
- Add `depth_tokenizer` and `depth_cross_attn` parameter groups by module-name filter in the optimizer setup. Both should share the same `lr=1e-4` group for simplicity; they can be split into separate groups if per-module LR tuning is needed later.
- Add `fusion_strategy = "late_cross_attention"` attribute to `_Cfg` for logging.
- Change `_Cfg.output_dir` to `"runs/idea001/design003"`.
- The `Pose3DHead` receives the same `(B, 1024, 40, 24)` feature map as in the baseline — **no changes to the head are required**.
- Verify that `self.vit.ln1` (or `self.vit.norm`) is applied inside the ViT's own `forward` before returning the feature map. If it is applied externally in `SapiensBackboneMidFusion.forward` (as noted in design002), replicate the same convention here.
