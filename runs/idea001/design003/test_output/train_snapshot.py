"""Training script for SapiensPose3D on BEDLAM2 — design003: late_cross_attention.

Stable infrastructure (constants, splits, logging, visualization, checkpoints)
lives in infra.py — edit only this file when changing the model, loss,
augmentation, or hyperparameters.

"""

from __future__ import annotations

import math
import os
import random
import resource
import sys
import time
from collections import OrderedDict
from pathlib import Path

# ── Raise the open-file-descriptor limit ─────────────────────────────────────
_soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (min(65536, _hard), _hard))

# ── Reduce CUDA memory fragmentation ─────────────────────────────────────────
# The DepthCrossAttention FFN (1024→4096→1024) is memory-intensive; expandable
# segments allows the allocator to reuse fragmented memory more efficiently.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# ── Make mmpretrain importable (backbone depends on it) ──────────────────────
_SAPIENS_ROOT = Path("/work/pi_nwycoff_umass_edu/hang/auto/sapiens")
for _p in [str(_SAPIENS_ROOT / "pretrain"), str(_SAPIENS_ROOT / "engine")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.amp import GradScaler
from torch.utils.checkpoint import checkpoint as grad_ckpt
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm

from mmpretrain.models.backbones.vision_transformer import VisionTransformer
from mmpretrain.models.utils import resize_pos_embed

from infra import (
    # constants
    NUM_JOINTS, PELVIS_IDX, ACTIVE_JOINT_INDICES,
    FLIP_PAIRS, RGB_MEAN, RGB_STD, DEPTH_MAX_METERS,
    BATCH_SIZE, ACCUM_STEPS, RANDOM_SEED,
    # splits
    get_splits,
    # collate
    collate_fn,
    # weight loading util
    _interp_pos_embed,
    # logging
    Logger, _CSV_FIELDNAMES, IterLogger,
    # checkpoints
    save_checkpoint, load_checkpoint,
    validate, pose_loss, mpjpe, recover_pelvis_3d, pelvis_abs_error, BODY_IDX, HAND_IDX
)


# ── TRANSFORMS ───────────────────────────────────────────────────────────────

class Resize:
    """Resize RGB and depth to (out_h, out_w). Updates intrinsic K."""

    def __init__(self, out_h: int, out_w: int):
        self.out_h = out_h
        self.out_w = out_w

    def __call__(self, sample: dict) -> dict:
        rgb: np.ndarray = sample["rgb"]
        orig_h, orig_w = rgb.shape[:2]
        scale_x = self.out_w / orig_w
        scale_y = self.out_h / orig_h

        sample["rgb"] = cv2.resize(rgb, (self.out_w, self.out_h), interpolation=cv2.INTER_LINEAR)

        if sample.get("depth") is not None:
            sample["depth"] = cv2.resize(
                sample["depth"], (self.out_w, self.out_h), interpolation=cv2.INTER_NEAREST
            )

        K: np.ndarray = sample["intrinsic"].copy()
        K[0, 0] *= scale_x; K[1, 1] *= scale_y
        K[0, 2] *= scale_x; K[1, 2] *= scale_y
        sample["intrinsic"] = K
        return sample


class CropPerson:
    """Crop RGB + depth to the person bbox, expand to target aspect, resize.

    Falls back to plain Resize if no bbox key is present.
    """

    def __init__(self, out_h: int, out_w: int):
        self.out_h = out_h
        self.out_w = out_w

    def __call__(self, sample: dict) -> dict:
        if "bbox" not in sample:
            return Resize(self.out_h, self.out_w)(sample)

        bbox = sample["bbox"]
        rgb: np.ndarray = sample["rgb"]
        H, W = rgb.shape[:2]

        cx_box = (bbox[0] + bbox[2]) / 2.0
        cy_box = (bbox[1] + bbox[3]) / 2.0
        w_box  = max(bbox[2] - bbox[0], 1.0)
        h_box  = max(bbox[3] - bbox[1], 1.0)

        target_aspect = self.out_w / self.out_h
        if w_box / h_box < target_aspect:
            w_exp = h_box * target_aspect; h_exp = h_box
        else:
            h_exp = w_box / target_aspect; w_exp = w_box

        x0 = cx_box - w_exp / 2.0; y0 = cy_box - h_exp / 2.0
        x1 = cx_box + w_exp / 2.0; y1 = cy_box + h_exp / 2.0

        pad_left   = max(0, int(math.ceil(-x0)))
        pad_top    = max(0, int(math.ceil(-y0)))
        pad_right  = max(0, int(math.ceil(x1 - W)))
        pad_bottom = max(0, int(math.ceil(y1 - H)))

        depth = sample.get("depth")
        if depth is not None:
            dH, dW = depth.shape[:2]
            if dH != H or dW != W:
                depth = cv2.resize(depth, (W, H), interpolation=cv2.INTER_NEAREST)

        if any([pad_left, pad_top, pad_right, pad_bottom]):
            rgb = cv2.copyMakeBorder(
                rgb, pad_top, pad_bottom, pad_left, pad_right,
                cv2.BORDER_CONSTANT, value=(0, 0, 0),
            )
            if depth is not None:
                depth = cv2.copyMakeBorder(
                    depth, pad_top, pad_bottom, pad_left, pad_right,
                    cv2.BORDER_CONSTANT, value=0.0,
                )
            x0 += pad_left; y0 += pad_top; x1 += pad_left; y1 += pad_top

        ix0, iy0 = int(round(x0)), int(round(y0))
        ix1, iy1 = int(round(x1)), int(round(y1))
        crop_w = max(ix1 - ix0, 1); crop_h = max(iy1 - iy0, 1)
        sx = self.out_w / crop_w; sy = self.out_h / crop_h

        sample["rgb"] = cv2.resize(
            rgb[iy0:iy1, ix0:ix1], (self.out_w, self.out_h), interpolation=cv2.INTER_LINEAR
        )
        if depth is not None:
            sample["depth"] = cv2.resize(
                depth[iy0:iy1, ix0:ix1], (self.out_w, self.out_h), interpolation=cv2.INTER_NEAREST
            )

        orig_x0 = ix0 - pad_left; orig_y0 = iy0 - pad_top
        K: np.ndarray = sample["intrinsic"].copy()
        K[0, 0] *= sx; K[1, 1] *= sy
        K[0, 2] = (K[0, 2] - orig_x0) * sx
        K[1, 2] = (K[1, 2] - orig_y0) * sy
        sample["intrinsic"] = K
        return sample


class SubtractRoot:
    """Subtract pelvis from all joints; store pelvis_abs, pelvis_depth, pelvis_uv."""

    def __call__(self, sample: dict) -> dict:
        joints: np.ndarray = sample["joints"]
        pelvis_3d = joints[PELVIS_IDX].copy()
        sample["pelvis_abs"]   = pelvis_3d
        sample["joints"]       = joints - pelvis_3d[np.newaxis, :]
        sample["pelvis_depth"] = np.array([pelvis_3d[0]], dtype=np.float32)

        K = sample["intrinsic"]
        X, Y, Z = pelvis_3d[0], pelvis_3d[1], pelvis_3d[2]
        if X > 0.01:
            u_px = K[0, 0] * (-Y / X) + K[0, 2]
            v_px = K[1, 1] * (-Z / X) + K[1, 2]
        else:
            u_px, v_px = K[0, 2], K[1, 2]

        crop_h, crop_w = sample["rgb"].shape[:2]
        sample["pelvis_uv"] = np.array(
            [u_px / crop_w * 2.0 - 1.0, v_px / crop_h * 2.0 - 1.0], dtype=np.float32
        )
        return sample


class ToTensor:
    """RGB (H,W,3) uint8 → (3,H,W) float32 ImageNet-normalised.
       Depth (H,W) float32 → (1,H,W) float32 clipped & divided by DEPTH_MAX.
    """

    def __init__(self, rgb_mean=RGB_MEAN, rgb_std=RGB_STD, depth_max=DEPTH_MAX_METERS):
        self.mean      = np.array(rgb_mean, dtype=np.float32).reshape(1, 1, 3)
        self.std       = np.array(rgb_std,  dtype=np.float32).reshape(1, 1, 3)
        self.depth_max = depth_max

    def __call__(self, sample: dict) -> dict:
        rgb = (sample["rgb"].astype(np.float32) / 255.0 - self.mean) / self.std
        sample["rgb"] = torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1)))

        if sample.get("depth") is not None:
            depth = np.clip(sample["depth"], 0.0, self.depth_max) / self.depth_max
            sample["depth"] = torch.from_numpy(depth[np.newaxis])

        sample["joints"]    = torch.from_numpy(sample["joints"])
        sample["intrinsic"] = torch.from_numpy(sample["intrinsic"])
        for key in ("pelvis_abs", "pelvis_depth", "pelvis_uv"):
            if key in sample:
                sample[key] = torch.from_numpy(sample[key])
        return sample


class Compose:
    def __init__(self, transforms: list):
        self.transforms = transforms
    def __call__(self, sample: dict) -> dict:
        for t in self.transforms:
            sample = t(sample)
        return sample


def build_train_transform(out_h: int, out_w: int, scale_jitter: bool = True) -> Compose:
    return Compose([CropPerson(out_h, out_w), SubtractRoot(), ToTensor()])


def build_val_transform(out_h: int, out_w: int) -> Compose:
    return Compose([CropPerson(out_h, out_w), SubtractRoot(), ToTensor()])


# ── DATASET ───────────────────────────────────────────────────────────────────

_MIN_BBOX_PX = 32


class BedlamFrameDataset(Dataset):
    """One sample = one person × one frame from one BEDLAM2 sequence."""

    def __init__(self, seq_paths, data_root, transform=None,
                 depth_required=True):
        self.data_root      = data_root
        self.transform      = transform
        self.depth_required = depth_required
        self._label_cache: dict   = {}
        self._depth_mmap:  dict   = {}
        self._depth_cache: OrderedDict = OrderedDict()
        self._depth_cache_maxsize = 3

        self.index: list[tuple[str, int, int]] = []
        for seq_rel in seq_paths:
            label_path = os.path.join(data_root, "data", "label", seq_rel)
            try:
                with np.load(label_path, allow_pickle=True) as meta:
                    n_frames = int(meta["n_frames"])
                    n_body   = int(meta["joints_cam"].shape[0])
            except Exception as e:
                raise RuntimeError(f"Failed to read label {label_path}: {e}") from e
            for body_idx in range(n_body):
                for frame_idx in range(n_frames):
                    self.index.append((label_path, body_idx, frame_idx))

    def __len__(self):
        return len(self.index)

    def __getitem__(self, idx):
        for attempt in range(11):
            if attempt > 0:
                idx = random.randint(0, len(self.index) - 1)
            label_path, body_idx, frame_idx = self.index[idx]

            if label_path not in self._label_cache:
                with np.load(label_path, allow_pickle=True) as meta:
                    entry = {
                        "folder_name":      str(meta["folder_name"]),
                        "seq_name":         str(meta["seq_name"]),
                        "intrinsic_matrix": meta["intrinsic_matrix"].astype(np.float32),
                        "joints_cam":       meta["joints_cam"].astype(np.float32),
                        "joints_2d": meta["joints_2d"].astype(np.float32) if "joints_2d" in meta else None,
                    }
                    self._label_cache[label_path] = entry
            cached = self._label_cache[label_path]

            joints = cached["joints_cam"][body_idx, frame_idx]
            bbox   = self._compute_bbox(cached, body_idx, frame_idx)

            if bbox is not None:
                if bbox[2] - bbox[0] < _MIN_BBOX_PX or bbox[3] - bbox[1] < _MIN_BBOX_PX:
                    continue

            rgb = self._read_frame(cached["folder_name"], cached["seq_name"], frame_idx, label_path)

            # Far-person filter: skip if all joints at depth >= 10m
            # (axis 0 = forward/depth axis in BEDLAM2 camera space)
            if np.all(joints[:, 0] >= 10.0):
                continue

            if cached["joints_2d"] is not None:
                H_raw, W_raw = rgb.shape[:2]
                kpts = cached["joints_2d"][body_idx, frame_idx]
                oob = (kpts[:, 0] < 0) | (kpts[:, 0] >= W_raw) | \
                      (kpts[:, 1] < 0) | (kpts[:, 1] >= H_raw)
                # OOB filter: skip if >= 50% of joints are outside image
                if float(np.sum(oob)) / kpts.shape[0] >= 0.50:
                    continue
                # Visibility filter: skip if fewer than 8 joints are visible
                if int(np.sum(~oob)) < 8:
                    continue

            joints = joints[ACTIVE_JOINT_INDICES]

            npy_path = os.path.join(self.data_root, "data", "depth", "npy",
                                    cached["folder_name"], f"{cached['seq_name']}.npy")
            npz_path = os.path.join(self.data_root, "data", "depth", "npz",
                                    cached["folder_name"], f"{cached['seq_name']}.npz")
            depth = self._read_depth(npy_path, npz_path, frame_idx, label_path)

            H, W = rgb.shape[:2]
            if bbox is not None:
                bbox = np.clip(bbox, [0, 0, 0, 0],
                               [float(W), float(H), float(W), float(H)]).astype(np.float32)

            sample = {
                "rgb": rgb, "depth": depth, "joints": joints,
                "intrinsic": cached["intrinsic_matrix"],
                "folder_name": cached["folder_name"], "seq_name": cached["seq_name"],
                "frame_idx": frame_idx, "body_idx": body_idx,
            }
            if bbox is not None:
                sample["bbox"] = bbox

            if self.transform is not None:
                sample = self.transform(sample)
            return sample

        return sample  # type: ignore[possibly-undefined]

    def _compute_bbox(self, cached, body_idx, frame_idx):
        if cached["joints_2d"] is None:
            return None
        kpts = cached["joints_2d"][body_idx, frame_idx]
        x_min, y_min = kpts[:, 0].min(), kpts[:, 1].min()
        x_max, y_max = kpts[:, 0].max(), kpts[:, 1].max()
        w = x_max - x_min; h = y_max - y_min
        return np.array([x_min - w * 0.1, y_min - h * 0.1,
                          x_max + w * 0.1, y_max + h * 0.1], dtype=np.float32)

    def _read_frame(self, folder_name, seq_name, frame_idx, label_path):
        jpeg_path = Path(self.data_root) / "data" / "frames" / folder_name / seq_name / f"{frame_idx:05d}.jpg"
        if not jpeg_path.exists():
            raise FileNotFoundError(
                f"Missing extracted JPG frame for {label_path}: {jpeg_path}. "
                "Run extract_frames.py first."
            )
        img = cv2.imread(str(jpeg_path))
        if img is None:
            raise RuntimeError(f"Failed to decode JPG frame: {jpeg_path}")
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    def _read_depth(self, npy_path, npz_path, frame_idx, label_path):
        if npy_path not in self._depth_mmap:
            self._depth_mmap[npy_path] = np.load(npy_path, mmap_mode="r") if os.path.exists(npy_path) else None
        arr = self._depth_mmap[npy_path]
        if arr is not None:
            return arr[frame_idx].astype(np.float32)

        if npz_path not in self._depth_cache:
            if not os.path.exists(npz_path):
                if self.depth_required:
                    raise FileNotFoundError(f"Depth not found for {label_path}: {npz_path}")
                val = None
            else:
                with np.load(npz_path) as f:
                    val = f["depth"].astype(np.float32)
            if len(self._depth_cache) >= self._depth_cache_maxsize:
                self._depth_cache.popitem(last=False)
            self._depth_cache[npz_path] = val
        else:
            self._depth_cache.move_to_end(npz_path)
        arr = self._depth_cache[npz_path]
        return None if arr is None else arr[frame_idx]


def build_dataloader(seq_paths, data_root, transform=None, depth_required=True,
                     batch_size=16, shuffle=True, num_workers=4, prefetch_factor=2,
                     worker_init_fn=None):
    dataset = BedlamFrameDataset(seq_paths=seq_paths, data_root=data_root,
                                 transform=transform, depth_required=depth_required)
    return DataLoader(
        dataset, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers,
        collate_fn=collate_fn, pin_memory=torch.cuda.is_available(),
        persistent_workers=False,
        prefetch_factor=(prefetch_factor if num_workers > 0 else None),
        multiprocessing_context=("spawn" if num_workers > 0 else None),
        worker_init_fn=worker_init_fn,
    )


# ── MODEL CONFIG ──────────────────────────────────────────────────────────────

SAPIENS_ARCHS = {
    "sapiens_0.3b": dict(embed_dim=1024, num_layers=24),
    "sapiens_0.6b": dict(embed_dim=1280, num_layers=32),
    "sapiens_1b":   dict(embed_dim=1536, num_layers=40),
    "sapiens_2b":   dict(embed_dim=1920, num_layers=48),
}


# ── BACKBONE ──────────────────────────────────────────────────────────────────

def _get_patch_grid(vit) -> tuple:
    """Return (n_h, n_w) patch grid from a VisionTransformer instance."""
    try:
        return tuple(vit.patch_resolution)
    except AttributeError:
        pass
    # Fallback: known values for sapiens_0.3b at (640, 384)
    return (40, 24)


class DepthTokenizer(nn.Module):
    """Encode (B, 1, 640, 384) depth to (B, 960, 64) depth token sequence.

    Conv2d(1, 64, kernel_size=16, stride=16, padding=2) → (B, 64, 40, 24)
    flatten + transpose → (B, 960, 64)
    LayerNorm(64) → (B, 960, 64)

    The Conv2d weight and bias are zero-initialized so depth tokens are all-zero
    at epoch 0, ensuring the cross-attention residual starts silent.
    """

    def __init__(self, depth_embed_dim: int = 64, patch_size: int = 16,
                 img_h: int = 640, img_w: int = 384, padding: int = 2):
        super().__init__()
        # padding=2 matches RGB patch embed → spatial output (40, 24)
        self.depth_patch_embed = nn.Conv2d(
            1, depth_embed_dim, kernel_size=patch_size, stride=patch_size, padding=padding,
        )
        self.depth_norm = nn.LayerNorm(depth_embed_dim)
        # Zero-init: depth tokens are all-zero at epoch 0
        nn.init.zeros_(self.depth_patch_embed.weight)
        nn.init.zeros_(self.depth_patch_embed.bias)

    def forward(self, depth: torch.Tensor) -> torch.Tensor:
        # depth: (B, 1, H, W)
        x = self.depth_patch_embed(depth)   # (B, 64, 40, 24)
        x = x.flatten(2).transpose(1, 2)    # (B, 960, 64)
        x = self.depth_norm(x)              # (B, 960, 64)
        return x


class DepthCrossAttention(nn.Module):
    """Single transformer decoder-style block: RGB tokens attend to depth tokens.

    RGB tokens (queries) × depth tokens (keys + values) → updated RGB tokens.

    Architecture (pre-norm + residual):
        norm_q   : LayerNorm(rgb_dim)
        norm_d   : LayerNorm(depth_dim)
        q_proj   : Linear(rgb_dim, qk_dim)
        k_proj   : Linear(depth_dim, qk_dim)
        v_proj   : Linear(depth_dim, qk_dim)
        out_proj : Linear(qk_dim, rgb_dim)   ← zero-initialized
        ffn_norm : LayerNorm(rgb_dim)
        ffn      : Linear(rgb_dim, 4*rgb_dim) → GELU → Dropout → Linear → Dropout
    """

    def __init__(self, rgb_dim: int = 1024, depth_dim: int = 64,
                 qk_dim: int = 256, num_heads: int = 8, dropout: float = 0.1):
        super().__init__()
        assert qk_dim % num_heads == 0, "qk_dim must be divisible by num_heads"
        self.rgb_dim   = rgb_dim
        self.depth_dim = depth_dim
        self.qk_dim    = qk_dim
        self.num_heads = num_heads
        self.head_dim  = qk_dim // num_heads
        self.dropout_p = dropout

        self.q_proj   = nn.Linear(rgb_dim,   qk_dim, bias=True)
        self.k_proj   = nn.Linear(depth_dim, qk_dim, bias=True)
        self.v_proj   = nn.Linear(depth_dim, qk_dim, bias=True)
        self.out_proj = nn.Linear(qk_dim, rgb_dim,   bias=True)
        self.attn_drop = nn.Dropout(dropout)

        self.norm_q   = nn.LayerNorm(rgb_dim)
        self.norm_d   = nn.LayerNorm(depth_dim)
        self.ffn_norm = nn.LayerNorm(rgb_dim)
        self.ffn = nn.Sequential(
            nn.Linear(rgb_dim, 4 * rgb_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(4 * rgb_dim, rgb_dim),
            nn.Dropout(dropout),
        )

        self._init_weights()

    def _init_weights(self):
        # q/k/v projections: Xavier uniform (standard transformer init)
        for proj in (self.q_proj, self.k_proj, self.v_proj):
            nn.init.xavier_uniform_(proj.weight)
            nn.init.zeros_(proj.bias)
        # out_proj: zero-init → cross-attention residual is zero at epoch 0
        nn.init.zeros_(self.out_proj.weight)
        nn.init.zeros_(self.out_proj.bias)
        # FFN: Xavier uniform
        for m in self.ffn.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.zeros_(m.bias)
        # LayerNorms: standard (weight=1, bias=0) — already default

    def forward(self, x: torch.Tensor, d: torch.Tensor) -> torch.Tensor:
        # x: (B, N, rgb_dim)   — RGB tokens (queries)
        # d: (B, N, depth_dim) — depth tokens (keys and values)
        B, N, _ = x.shape

        # --- Cross-attention sub-layer (pre-norm) ---
        xn = self.norm_q(x)   # (B, N, rgb_dim)
        dn = self.norm_d(d)   # (B, N, depth_dim)

        Q = self.q_proj(xn)   # (B, N, qk_dim)
        K = self.k_proj(dn)   # (B, N, qk_dim)
        V = self.v_proj(dn)   # (B, N, qk_dim)

        # Reshape to multi-head: (B, num_heads, N, head_dim)
        Q = Q.view(B, N, self.num_heads, self.head_dim).transpose(1, 2)
        K = K.view(B, N, self.num_heads, self.head_dim).transpose(1, 2)
        V = V.view(B, N, self.num_heads, self.head_dim).transpose(1, 2)

        # Scaled dot-product attention (memory-efficient: does not materialize attn matrix)
        # PyTorch >= 2.1 supports scale kwarg; 2.6 is confirmed available here.
        ctx = F.scaled_dot_product_attention(
            Q, K, V,
            dropout_p=self.dropout_p if self.training else 0.0,
            scale=self.head_dim ** -0.5,
        )   # (B, num_heads, N, head_dim)
        ctx   = ctx.transpose(1, 2).reshape(B, N, self.qk_dim)   # (B, N, qk_dim)
        ctx   = self.out_proj(ctx)                   # (B, N, rgb_dim)

        x = x + ctx   # residual

        # --- FFN sub-layer (pre-norm) ---
        x = x + self.ffn(self.ffn_norm(x))

        return x   # (B, N, rgb_dim)


class SapiensBackboneLateFusion(nn.Module):
    """Sapiens ViT (3-ch, unchanged) + post-backbone DepthCrossAttention adapter.

    The ViT backbone runs entirely on RGB. After the ViT produces a spatial
    feature map (B, 1024, 40, 24), it is flattened to (B, 960, 1024) and
    refined by DepthCrossAttention using depth tokens from DepthTokenizer.
    The result is reshaped back to (B, 1024, 40, 24) for Pose3DHead.
    """

    def __init__(self, arch="sapiens_0.3b", img_size=(640, 384), drop_path_rate=0.0,
                 depth_embed_dim: int = 64, qk_dim: int = 256,
                 num_heads: int = 8, dropout: float = 0.1):
        super().__init__()
        if arch not in SAPIENS_ARCHS:
            raise ValueError(f"Unknown arch '{arch}'. Choose from {list(SAPIENS_ARCHS)}")
        self.arch      = arch
        self.embed_dim = SAPIENS_ARCHS[arch]["embed_dim"]

        # Standard 3-channel ViT — pretrained weights load without modification
        self.vit = VisionTransformer(
            arch=arch, img_size=img_size, patch_size=16, in_channels=3,
            qkv_bias=True, final_norm=True, drop_path_rate=drop_path_rate,
            with_cls_token=False, out_type="featmap", patch_cfg=dict(padding=2),
        )
        self.depth_tokenizer = DepthTokenizer(
            depth_embed_dim=depth_embed_dim, patch_size=16,
            img_h=img_size[0], img_w=img_size[1], padding=2,
        )
        self.depth_cross_attn = DepthCrossAttention(
            rgb_dim=self.embed_dim, depth_dim=depth_embed_dim,
            qk_dim=qk_dim, num_heads=num_heads, dropout=dropout,
        )

    def _run_vit_with_ckpt(self, rgb: torch.Tensor) -> torch.Tensor:
        """Manually iterate ViT layers with per-layer gradient checkpointing.

        Replicates VisionTransformer.forward for the with_cls_token=False case.
        Each transformer block is wrapped in grad_ckpt to avoid storing its
        intermediate activations, substantially reducing peak VRAM usage.
        """
        vit = self.vit
        B = rgb.size(0)

        x, patch_resolution = vit.patch_embed(rgb)   # (B, N, C)

        x = x + resize_pos_embed(
            vit.pos_embed, vit.patch_resolution, patch_resolution,
            mode=vit.interpolate_mode, num_extra_tokens=vit.num_extra_tokens,
        )
        x = vit.drop_after_pos(x)
        x = vit.pre_norm(x)

        n_layers = len(vit.layers)
        for i, layer in enumerate(vit.layers):
            if self.training:
                x = grad_ckpt(layer, x, use_reentrant=False)
            else:
                x = layer(x)
            if i == n_layers - 1 and vit.final_norm:
                x = vit.ln1(x)

        # (B, N, C) -> (B, C, n_h, n_w)
        n_h, n_w = patch_resolution
        x = x.transpose(1, 2).reshape(B, self.embed_dim, n_h, n_w)
        return x

    def forward(self, rgb: torch.Tensor, depth: torch.Tensor) -> torch.Tensor:
        # rgb:   (B, 3, H, W)
        # depth: (B, 1, H, W)

        # 1. Run full ViT on RGB only — with per-layer gradient checkpointing
        feat = self._run_vit_with_ckpt(rgb)   # (B, 1024, 40, 24)

        B, C, H_p, W_p = feat.shape

        # 2. Flatten feature map to token sequence
        x = feat.flatten(2).transpose(1, 2)   # (B, 960, 1024)

        # 3. Encode depth to token sequence
        d = self.depth_tokenizer(depth)        # (B, 960, 64)

        # 4. Cross-attention: RGB tokens attend to depth tokens.
        # Gradient checkpointing saves the ~60MB FFN activation in the fwd pass.
        if self.training:
            x = grad_ckpt(self.depth_cross_attn, x, d, use_reentrant=False)
        else:
            x = self.depth_cross_attn(x, d)    # (B, 960, 1024)

        # 5. Reshape back to feature map for Pose3DHead
        x = x.transpose(1, 2).reshape(B, C, H_p, W_p)   # (B, 1024, 40, 24)

        return x


# ── HEAD ──────────────────────────────────────────────────────────────────────

class Pose3DHead(nn.Module):
    """Transformer decoder head.

    Learnable joint queries (num_joints × hidden_dim) cross-attend to the
    flattened backbone feature map, then a per-joint linear predicts (x,y,z).

    Architecture:
        input_proj : Linear(in_channels → hidden_dim)
        joint_queries : Embedding(num_joints, hidden_dim)
        decoder : TransformerDecoder (num_layers layers, num_heads heads)
        joints_out : Linear(hidden_dim → 3)
    """

    def __init__(self, in_channels, num_joints=NUM_JOINTS, hidden_dim=256,
                 num_heads=8, num_layers=4, dropout=0.1):
        super().__init__()
        self.num_joints   = num_joints
        self.input_proj   = nn.Linear(in_channels, hidden_dim)
        self.joint_queries = nn.Embedding(num_joints, hidden_dim)
        decoder_layer = nn.TransformerDecoderLayer(
            d_model=hidden_dim, nhead=num_heads,
            dim_feedforward=hidden_dim * 4, dropout=dropout,
            batch_first=True, norm_first=True,
        )
        self.decoder    = nn.TransformerDecoder(decoder_layer, num_layers=num_layers)
        self.joints_out = nn.Linear(hidden_dim, 3)
        # Pelvis branches: query[0] (pelvis token) → depth + UV
        self.depth_out  = nn.Linear(hidden_dim, 1)   # (B, 1) forward dist in metres
        self.uv_out     = nn.Linear(hidden_dim, 2)   # (B, 2) normalised [-1, 1]
        self._init_weights()

    def _init_weights(self):
        nn.init.trunc_normal_(self.joint_queries.weight, std=0.02)
        for m in [self.joints_out, self.depth_out, self.uv_out]:
            nn.init.trunc_normal_(m.weight, std=0.02)
            nn.init.zeros_(m.bias)

    def forward(self, feat: torch.Tensor) -> dict[str, torch.Tensor]:
        B = feat.size(0)
        # (B, C, H, W) → (B, H*W, hidden_dim)
        memory = self.input_proj(feat.flatten(2).transpose(1, 2))
        # (B, num_joints, hidden_dim)
        queries = self.joint_queries.weight.unsqueeze(0).expand(B, -1, -1)
        out = self.decoder(queries, memory)               # (B, num_joints, hidden_dim)
        pelvis_token = out[:, 0, :]                       # (B, hidden_dim) — pelvis query
        return {
            "joints":       self.joints_out(out),         # (B, num_joints, 3)
            "pelvis_depth": self.depth_out(pelvis_token), # (B, 1)
            "pelvis_uv":    self.uv_out(pelvis_token),    # (B, 2)
        }


# ── WEIGHT LOADING ────────────────────────────────────────────────────────────

def load_sapiens_pretrained(model: nn.Module, ckpt_path: str, verbose: bool = True) -> None:
    """Load Sapiens RGB pretrain checkpoint into SapiensBackboneLateFusion.

    The patch embed is 3-channel in this design, so weights load directly
    without any channel expansion. DepthTokenizer and DepthCrossAttention
    weights are deliberately not loaded from the checkpoint (zero/Xavier init).
    """
    ckpt_path = Path(ckpt_path)
    if not ckpt_path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {ckpt_path}")

    raw = torch.load(ckpt_path, map_location="cpu", weights_only=True)
    src = raw.get("state_dict", raw.get("model", raw))

    remapped = {f"backbone.vit.{k}": v for k, v in src.items()}
    model_sd = model.state_dict()

    # Interpolate pos_embed if spatial resolution differs
    pe_key = "backbone.vit.pos_embed"
    if pe_key in remapped and pe_key in model_sd:
        src_pe = remapped[pe_key]
        try:
            tgt_h, tgt_w = model.backbone.vit.patch_resolution
        except AttributeError:
            tgt_h, tgt_w = _get_patch_grid(model.backbone.vit)
        src_g = int((src_pe.shape[1] - 1) ** 0.5)
        remapped[pe_key] = _interp_pos_embed(src_pe, tgt_h, tgt_w, has_cls=True).to(src_pe.dtype)
        if verbose:
            print(f"[weights] pos_embed: {src_g}x{src_g} -> {tgt_h}x{tgt_w}  (bicubic)")

    remapped.pop("backbone.vit.cls_token", None)

    load_sd, missing, shape_mismatch = {}, [], []
    for k, v_model in model_sd.items():
        # Skip DepthTokenizer and DepthCrossAttention — intentionally not loaded
        if k.startswith("backbone.depth_tokenizer.") or k.startswith("backbone.depth_cross_attn."):
            continue
        if not k.startswith("backbone."):
            continue
        if k not in remapped:
            missing.append(k); continue
        if v_model.shape != remapped[k].shape:
            shape_mismatch.append(f"  {k}: model {v_model.shape} vs ckpt {remapped[k].shape}"); continue
        load_sd[k] = remapped[k]

    model.load_state_dict(load_sd, strict=False)
    if verbose:
        n_bb = sum(1 for k in model_sd if k.startswith("backbone."))
        print(f"[weights] Loaded {len(load_sd)} / {n_bb} backbone tensors")
        print(f"[weights] DepthTokenizer: zero-init (not loaded from checkpoint)")
        print(f"[weights] DepthCrossAttention: Xavier/zero-init (not loaded from checkpoint)")
        print(f"[weights] Head ({sum(1 for k in model_sd if k.startswith('head.'))} tensors) randomly initialised")
        if missing:
            print(f"[weights] Missing ({len(missing)}): {missing[:5]}{'...' if len(missing) > 5 else ''}")
        if shape_mismatch:
            print(f"[weights] Shape mismatch ({len(shape_mismatch)}):")
            for s in shape_mismatch: print(s)


# ── FULL MODEL ────────────────────────────────────────────────────────────────

class SapiensPose3D(nn.Module):
    """Backbone + Head wrapper for late cross-attention fusion.

    Accepts a concatenated (B, 4, H, W) tensor (rgb channels 0:3, depth
    channel 3:4) and splits it before passing to SapiensBackboneLateFusion.
    This keeps the interface compatible with infra.validate which concatenates
    rgb+depth before calling model(x).
    """

    def __init__(self, arch="sapiens_0.3b", img_size=(640, 384), num_joints=NUM_JOINTS,
                 head_hidden=256, head_num_heads=8, head_num_layers=4,
                 head_dropout=0.1, drop_path_rate=0.0,
                 depth_embed_dim: int = 64, qk_dim: int = 256,
                 attn_num_heads: int = 8, attn_dropout: float = 0.1):
        super().__init__()
        self.backbone = SapiensBackboneLateFusion(
            arch=arch, img_size=img_size, drop_path_rate=drop_path_rate,
            depth_embed_dim=depth_embed_dim, qk_dim=qk_dim,
            num_heads=attn_num_heads, dropout=attn_dropout,
        )
        self.head = Pose3DHead(in_channels=SAPIENS_ARCHS[arch]["embed_dim"],
                               num_joints=num_joints, hidden_dim=head_hidden,
                               num_heads=head_num_heads, num_layers=head_num_layers,
                               dropout=head_dropout)

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        # x: (B, 4, H, W) — rgb in channels 0:3, depth in channel 3:
        rgb   = x[:, :3]    # (B, 3, H, W)
        depth = x[:, 3:]    # (B, 1, H, W)
        feat = self.backbone(rgb, depth)
        return self.head(feat)

    def load_pretrained(self, ckpt_path: str, verbose: bool = True) -> None:
        load_sapiens_pretrained(self, ckpt_path, verbose=verbose)


# ── CONFIG ────────────────────────────────────────────────────────────────────

class _Cfg:
    # Paths
    data_root   = "/work/pi_nwycoff_umass_edu/hang/BEDLAM2subset"
    pretrain    = "/home/hangyang_umass_edu/MMC/sapiens/pretrain/checkpoints/sapiens_0.3b/sapiens_0.3b_epoch_1600_clean.pth"
    output_dir  = "/work/pi_nwycoff_umass_edu/hang/auto/runs/idea001/design003"
    resume      = ""

    # Fusion strategy label
    fusion_strategy = "late_cross_attention"

    # Model
    arch        = "sapiens_0.3b"
    img_h       = 640
    img_w       = 384
    head_hidden     = 256
    head_num_heads  = 8
    head_num_layers = 4
    head_dropout    = 0.1
    drop_path       = 0.1

    # Training
    epochs              = 20
    batch_size          = BATCH_SIZE
    num_workers         = 4
    lr_backbone         = 1e-5
    lr_depth_adapter    = 1e-4
    lr_head             = 1e-4
    weight_decay        = 0.03
    warmup_epochs= 3
    grad_clip    = 1.0
    accum_steps  = ACCUM_STEPS
    amp          = False  # M40 has no FP16 tensor cores
    patience     = 0

    # Loss weights
    lambda_depth = 0.1
    lambda_uv    = 0.2

    # Data splits
    splits_file      = "/work/pi_nwycoff_umass_edu/hang/auto/splits_rome_tracking.json"  # "" = auto-split
    val_ratio        = 0.1
    test_ratio       = 0.1
    seed             = 2026
    single_body_only = False
    max_train_seqs   = 0    # 0 = no cap
    max_val_seqs     = 0    # 0 = no cap

    # Logging / checkpoints
    log_interval  = 50
    save_interval = 1
    val_interval  = 1
    max_batches   = 0
    no_scale_jitter = False


def get_config():
    return _Cfg()


# ── LR SCHEDULE ───────────────────────────────────────────────────────────────

def get_lr_scale(epoch: int, total_epochs: int, warmup_epochs: int) -> float:
    """Linear warmup then cosine decay."""
    if epoch < warmup_epochs:
        return (epoch + 1) / warmup_epochs
    progress = (epoch - warmup_epochs) / max(1, total_epochs - warmup_epochs)
    return 0.5 * (1.0 + math.cos(math.pi * progress))


# ── TRAIN / VAL LOOPS ────────────────────────────────────────────────────────

def train_one_epoch(model, loader, optimizer, scaler, device, epoch, args,
                    iter_logger=None) -> dict:
    model.train()
    optimizer.zero_grad()
    total = {k: 0.0 for k in ("loss", "pose", "mpjpe_body", "pelvis_err", "weighted")}
    n = 0
    pbar = tqdm(loader, total=args.max_batches or len(loader),
                desc=f"Epoch {epoch} [train]", leave=True, dynamic_ncols=True)

    for i, batch in enumerate(pbar):
        rgb           = batch["rgb"].to(device, non_blocking=True)
        depth         = batch["depth"].to(device, non_blocking=True)
        joints        = batch["joints"].to(device, non_blocking=True)
        gt_pelvis_abs = batch["pelvis_abs"].to(device, non_blocking=True)   # (B, 3)
        gt_pd         = batch["pelvis_depth"].to(device, non_blocking=True) # (B, 1)
        gt_uv         = batch["pelvis_uv"].to(device, non_blocking=True)    # (B, 2)
        K             = batch["intrinsic"].to(device, non_blocking=True)    # (B, 3, 3)
        x = torch.cat([rgb, depth], dim=1)

        with torch.amp.autocast("cuda", enabled=args.amp):
            out    = model(x)
            l_pose = pose_loss(out["joints"][:, BODY_IDX], joints[:, BODY_IDX])
            l_dep  = pose_loss(out["pelvis_depth"], gt_pd)
            l_uv   = pose_loss(out["pelvis_uv"],    gt_uv)
            loss   = (l_pose + args.lambda_depth * l_dep + args.lambda_uv * l_uv) / args.accum_steps

        scaler.scale(loss).backward()

        if (i + 1) % args.accum_steps == 0:
            if args.grad_clip > 0:
                scaler.unscale_(optimizer)
                nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad()

        with torch.no_grad():
            pf   = out["joints"].float()
            body = mpjpe(pf, joints, BODY_IDX).item()
            pe   = pelvis_abs_error(out["pelvis_depth"].float(), out["pelvis_uv"].float(),
                                    gt_pelvis_abs, K, args.img_h, args.img_w).item()
            total["loss"]       += loss.item() * args.accum_steps
            total["pose"]       += l_pose.item()
            total["mpjpe_body"] += body
            total["pelvis_err"] += pe
            total["weighted"]   += 0.67 * body + 0.33 * pe
            if iter_logger is not None:
                iter_logger.log({"epoch": epoch, "iter": n,
                                 "loss": loss.item() * args.accum_steps,
                                 "loss_pose": l_pose.item(),
                                 "loss_depth": l_dep.item(),
                                 "loss_uv": l_uv.item(),
                                 "mpjpe_body": body, "pelvis_err": pe,
                                 "mpjpe_weighted": 0.67 * body + 0.33 * pe})
        del x, out, l_pose, l_dep, l_uv, loss
        n += 1
        if n == 1:
            alloc = torch.cuda.memory_allocated(device) / 1024**3
            reserv = torch.cuda.memory_reserved(device) / 1024**3
            pbar.write(f"[GPU mem after batch 1] allocated={alloc:.2f}GB  reserved={reserv:.2f}GB")
        pbar.set_postfix(loss=f"{total['loss']/n:.4f}",
                         body=f"{total['mpjpe_body']/n:.1f}mm",
                         pelvis=f"{total['pelvis_err']/n:.1f}mm",
                         w=f"{total['weighted']/n:.1f}mm")
        if args.max_batches > 0 and n >= args.max_batches:
            break

    pbar.close()
    n = max(1, n)
    return {
        "train_loss":        total["loss"] / n,
        "train_loss_pose":   total["pose"] / n,
        "train_mpjpe_body":  total["mpjpe_body"] / n,
        "train_pelvis_err":  total["pelvis_err"] / n,
        "train_mpjpe_weighted": total["weighted"] / n,
    }


def _worker_init_fn(worker_id: int):
    seed = 2026 + worker_id
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def main():
    # Global determinism
    random.seed(2026)
    np.random.seed(2026)
    torch.manual_seed(2026)
    torch.cuda.manual_seed_all(2026)

    args    = get_config()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}\nOutput: {out_dir}")

    # Save a snapshot of this script at the start of training
    import shutil as _shutil
    _shutil.copy(__file__, str(out_dir / "train_snapshot.py"))
    print(f"  Saved script snapshot → {out_dir}/train_snapshot.py")

    # Data
    print("\nBuilding data splits ...")
    if args.splits_file:
        import json as _json
        with open(args.splits_file) as _f:
            _sp = _json.load(_f)
        train_seqs = _sp["train"]
        val_seqs   = _sp["val"]
        print(f"  Loaded splits from {args.splits_file}")
    else:
        train_seqs, val_seqs, _ = get_splits(
            overview_path=str(Path(args.data_root) / "data" / "overview.txt"),
            val_ratio=args.val_ratio, test_ratio=args.test_ratio, seed=args.seed,
            single_body_only=args.single_body_only, skip_missing_body=True,
            depth_required=True, mp4_required=False,
            frames_root=str(Path(args.data_root) / "data" / "frames"),
        )
    if args.max_train_seqs > 0:
        train_seqs = train_seqs[:args.max_train_seqs]
    if args.max_val_seqs > 0:
        val_seqs = val_seqs[:args.max_val_seqs]
    print(f"  Sequences — train: {len(train_seqs)}, val: {len(val_seqs)}")

    train_tf = build_train_transform(args.img_h, args.img_w)
    val_tf   = build_val_transform(args.img_h, args.img_w)
    train_loader = build_dataloader(train_seqs, args.data_root, train_tf,
                                    batch_size=args.batch_size, shuffle=True,
                                    num_workers=args.num_workers,
                                    worker_init_fn=_worker_init_fn)
    val_loader   = build_dataloader(val_seqs,   args.data_root, val_tf,
                                    batch_size=args.batch_size, shuffle=False,
                                    num_workers=args.num_workers,
                                    worker_init_fn=_worker_init_fn)
    print(f"  Frames  — train: {len(train_loader.dataset)}, val: {len(val_loader.dataset)}")

    # Model
    print(f"\nBuilding {args.arch} ...")
    model = SapiensPose3D(
        arch=args.arch, img_size=(args.img_h, args.img_w), num_joints=NUM_JOINTS,
        head_hidden=args.head_hidden, head_num_heads=args.head_num_heads,
        head_num_layers=args.head_num_layers, head_dropout=args.head_dropout,
        drop_path_rate=args.drop_path,
        depth_embed_dim=64, qk_dim=256, attn_num_heads=8, attn_dropout=0.1,
    ).to(device)
    if args.pretrain and not args.resume:
        model.load_pretrained(args.pretrain)
    print(f"  Parameters: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M")

    # Optimizer — 3 groups: ViT backbone, depth adapter (tokenizer + cross-attn), Head
    # Depth adapter uses lr_depth_adapter (1e-4); grows from zero/Xavier init
    depth_adapter_params = (
        list(model.backbone.depth_tokenizer.parameters()) +
        list(model.backbone.depth_cross_attn.parameters())
    )
    optimizer = torch.optim.AdamW(
        [{"params": model.backbone.vit.parameters(),  "lr": args.lr_backbone},
         {"params": depth_adapter_params,              "lr": args.lr_depth_adapter},
         {"params": model.head.parameters(),           "lr": args.lr_head}],
        weight_decay=args.weight_decay,
    )
    scaler = GradScaler("cuda", enabled=args.amp)

    # Resume
    start_epoch = 0
    best_mpjpe  = float("inf")
    if args.resume:
        start_epoch, best_mpjpe = load_checkpoint(model, optimizer, scaler, args.resume, device)

    logger      = Logger(str(out_dir / "metrics.csv"))
    iter_logger = IterLogger(str(out_dir / "iter_metrics.csv"))

    print(f"\nStarting training for {args.epochs} epochs ...\n")
    for g in optimizer.param_groups:
        g["initial_lr"] = g["lr"]
    patience_counter = 0

    for epoch in range(start_epoch, args.epochs):
        scale = get_lr_scale(epoch, args.epochs, args.warmup_epochs)
        for g in optimizer.param_groups:
            g["lr"] = g["initial_lr"] * scale
        lr_bb = optimizer.param_groups[0]["lr"]
        lr_hd = optimizer.param_groups[2]["lr"]
        print(f"Epoch {epoch+1}/{args.epochs}  lr_backbone={lr_bb:.2e}  lr_depth_adapter={optimizer.param_groups[1]['lr']:.2e}  lr_head={lr_hd:.2e}")

        t0 = time.time()
        train_m = train_one_epoch(model, train_loader, optimizer, scaler, device, epoch + 1, args,
                                  iter_logger=iter_logger)

        val_m = None
        if (epoch + 1) % args.val_interval == 0 or (epoch + 1) == args.epochs:
            val_m = validate(model, val_loader, device, args)
            torch.cuda.empty_cache()
            model.train()

        epoch_time = time.time() - t0
        print(f"  → loss={train_m['train_loss']:.4f}"
              f"  body={train_m['train_mpjpe_body']:.1f}mm"
              f"  pelvis={train_m['train_pelvis_err']:.1f}mm"
              f"  w={train_m['train_mpjpe_weighted']:.1f}mm", end="")
        if val_m:
            print(f"  | val body={val_m['val_mpjpe_body']:.1f}mm"
                  f"  pelvis={val_m['val_pelvis_err']:.1f}mm"
                  f"  w={val_m['val_mpjpe_weighted']:.1f}mm", end="")
        print(f"  ({epoch_time:.0f}s)\n")

        logger.log({"epoch": epoch + 1, "lr_backbone": lr_bb, "lr_head": lr_hd,
                    **train_m, **(val_m or {}), "epoch_time": epoch_time})

        if val_m:
            if val_m["val_mpjpe_weighted"] < best_mpjpe:
                best_mpjpe = val_m["val_mpjpe_weighted"]
                patience_counter = 0
                print(f"  *** New best weighted MPJPE = {best_mpjpe:.1f}mm"
                      f"  (body={val_m['val_mpjpe_body']:.1f}  pelvis={val_m['val_pelvis_err']:.1f}) ***\n")
            else:
                patience_counter += 1
                if args.patience > 0 and patience_counter >= args.patience:
                    print(f"  Early stopping at epoch {epoch + 1}")
                    break

    logger.close()
    iter_logger.close()
    print(f"Training complete. Best val weighted MPJPE = {best_mpjpe:.1f}mm")
    print(f"Checkpoints in {out_dir}/")

    # Report final val body MPJPE to stdout for the proxy pipeline
    final_val = val_m["val_mpjpe_body"] if val_m else float("nan")
    print(f"FINAL_VAL_MPJPE_BODY={final_val:.4f}")


if __name__ == "__main__":
    main()

