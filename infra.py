"""Infrastructure for SapiensPose3D training — stable, never-change utilities.

Contains:
  - SMPL-X constants (joint names, active indices, skeleton, flip pairs, normalization)
  - Data split utilities (get_seq_paths, split_sequences, get_splits)
  - collate_fn
  - Positional-embedding interpolation helper (_interp_pos_embed)
  - CSV Logger
  - Visualization (draw_pose_frame, build_val_video, visualize_fixed_samples, etc.)
  - Checkpoint helpers (save_checkpoint, load_checkpoint)

None of these depend on the model architecture, loss, or augmentation pipeline.
"""

from __future__ import annotations

import csv
import math
import os
import random
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm


# ── CONSTANTS ─────────────────────────────────────────────────────────────────

_NUM_JOINTS_RAW = 127
PELVIS_IDX = 0


JOINT_NAMES = [
    # 0-21: Core body
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee",
    "spine2", "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot",
    "neck", "left_collar", "right_collar", "head",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    # 22-24: Jaw and eyes (jaw=22 is excluded from active set)
    "jaw", "left_eye_smplhf", "right_eye_smplhf",
    # 25-39: Left hand
    "left_index1", "left_index2", "left_index3",
    "left_middle1", "left_middle2", "left_middle3",
    "left_pinky1", "left_pinky2", "left_pinky3",
    "left_ring1", "left_ring2", "left_ring3",
    "left_thumb1", "left_thumb2", "left_thumb3",
    # 40-54: Right hand
    "right_index1", "right_index2", "right_index3",
    "right_middle1", "right_middle2", "right_middle3",
    "right_pinky1", "right_pinky2", "right_pinky3",
    "right_ring1", "right_ring2", "right_ring3",
    "right_thumb1", "right_thumb2", "right_thumb3",
    # 55-126: Surface landmarks
    "nose", "right_eye", "left_eye", "right_ear", "left_ear",
    "left_big_toe", "left_small_toe", "left_heel",
    "right_big_toe", "right_small_toe", "right_heel",
    "left_thumb", "left_index", "left_middle", "left_ring", "left_pinky",
    "right_thumb", "right_index", "right_middle", "right_ring", "right_pinky",
    "right_eye_brow1", "right_eye_brow2", "right_eye_brow3", "right_eye_brow4", "right_eye_brow5",
    "left_eye_brow5", "left_eye_brow4", "left_eye_brow3", "left_eye_brow2", "left_eye_brow1",
    "nose1", "nose2", "nose3", "nose4",
    "right_nose_2", "right_nose_1", "nose_middle", "left_nose_1", "left_nose_2",
    "right_eye1", "right_eye2", "right_eye3", "right_eye4", "right_eye5", "right_eye6",
    "left_eye4", "left_eye3", "left_eye2", "left_eye1", "left_eye6", "left_eye5",
    "right_mouth_1", "right_mouth_2", "right_mouth_3", "mouth_top",
    "left_mouth_3", "left_mouth_2", "left_mouth_1",
    "left_mouth_5", "left_mouth_4", "mouth_bottom", "right_mouth_4", "right_mouth_5",
    "right_lip_1", "right_lip_2", "lip_top", "left_lip_2", "left_lip_1",
    "left_lip_3", "lip_bottom", "right_lip_3",
    "right_contour_1", "right_contour_2", "right_contour_3", "right_contour_4",
    "right_contour_5", "right_contour_6", "right_contour_7", "right_contour_8",
    "contour_middle",
    "left_contour_8", "left_contour_7", "left_contour_6", "left_contour_5",
    "left_contour_4", "left_contour_3", "left_contour_2", "left_contour_1",
]

ACTIVE_JOINT_INDICES = (
    list(range(0, 22))    # body (pelvis → right_wrist)
    + [23, 24]            # eyes (left_eye_smplhf, right_eye_smplhf)
    + list(range(25, 55)) # hands (left + right, 30 joints)
    + list(range(60, 76)) # non-face surface (toes, heels, fingertips)
)

NUM_JOINTS = len(ACTIVE_JOINT_INDICES)  # 70

_ORIG_TO_NEW = {orig: new for new, orig in enumerate(ACTIVE_JOINT_INDICES)}

_SMPLX_BONES_RAW = (
    (0, 3), (3, 6), (6, 9), (9, 12), (12, 15),
    (0, 1), (1, 4), (4, 7), (7, 10),
    (0, 2), (2, 5), (5, 8), (8, 11),
    (9, 13), (13, 16), (16, 18), (18, 20),
    (9, 14), (14, 17), (17, 19), (19, 21),
    (15, 23), (15, 24),
    (20, 25), (25, 26), (26, 27),
    (20, 28), (28, 29), (29, 30),
    (20, 31), (31, 32), (32, 33),
    (20, 34), (34, 35), (35, 36),
    (20, 37), (37, 38), (38, 39),
    (21, 40), (40, 41), (41, 42),
    (21, 43), (43, 44), (44, 45),
    (21, 46), (46, 47), (47, 48),
    (21, 49), (49, 50), (50, 51),
    (21, 52), (52, 53), (53, 54),
)
SMPLX_SKELETON = tuple(
    (_ORIG_TO_NEW[a], _ORIG_TO_NEW[b])
    for a, b in _SMPLX_BONES_RAW
    if a in _ORIG_TO_NEW and b in _ORIG_TO_NEW
)

FLIP_PAIRS = (
    (1, 2), (4, 5), (7, 8), (10, 11), (13, 14),
    (16, 17), (18, 19), (20, 21), (23, 24),
    (25, 40), (26, 41), (27, 42),
    (28, 43), (29, 44), (30, 45),
    (31, 46), (32, 47), (33, 48),
    (34, 49), (35, 50), (36, 51),
    (37, 52), (38, 53), (39, 54),
)

RGB_MEAN = (0.485, 0.456, 0.406)
RGB_STD  = (0.229, 0.224, 0.225)
DEPTH_MAX_METERS = 10.0

SOURCE_FPS   = 30
TARGET_FPS   = 6
FRAME_STRIDE = SOURCE_FPS // TARGET_FPS  # = 5

BATCH_SIZE   = 4
ACCUM_STEPS  = 8
RANDOM_SEED = 2026

# ── FIXED TRAINING CONSTANTS ──────────────────────────────────────────────────
# These never change across experiments and must not be treated as search axes.

DATA_ROOT    = "/work/pi_nwycoff_umass_edu/hang/BEDLAM2subset"
PRETRAIN_CKPT = "/home/hangyang_umass_edu/MMC/sapiens/pretrain/checkpoints/sapiens_0.3b/sapiens_0.3b_epoch_1600_clean.pth"
SPLITS_FILE  = "/work/pi_nwycoff_umass_edu/hang/auto/splits_rome_tracking.json"
VAL_RATIO    = 0.1
TEST_RATIO   = 0.1
SINGLE_BODY_ONLY = False

IMG_H        = 640
IMG_W        = 384

NUM_WORKERS  = 4
LOG_INTERVAL  = 50
SAVE_INTERVAL = 1
VAL_INTERVAL  = 1

_MIN_BBOX_PX = 32

SAPIENS_ARCHS = {
    "sapiens_0.3b": dict(embed_dim=1024, num_layers=24),
    "sapiens_0.6b": dict(embed_dim=1280, num_layers=32),
    "sapiens_1b":   dict(embed_dim=1536, num_layers=40),
    "sapiens_2b":   dict(embed_dim=1920, num_layers=48),
}


# ── DATA SPLITS ───────────────────────────────────────────────────────────────

def get_seq_paths(
    overview_path: str,
    single_body_only: bool = True,
    skip_missing_body: bool = True,
    depth_required: bool = True,
    mp4_required: bool = True,
    frames_root: str | None = None,
) -> list[str]:
    """Return filtered list of ``"folder/seq.npz"`` relative paths."""
    seq_paths = []
    with open(overview_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            name, conditions = line.split(":", 1)
            if single_body_only and "not_single_body=True" in conditions:
                continue
            if skip_missing_body and "missing_body=True" in conditions:
                continue
            if depth_required and "no_depth=True" in conditions:
                continue
            if mp4_required and "no_mp4=True" in conditions:
                continue
            folder, seq = name.strip().split("/")
            if frames_root is not None:
                if not (Path(frames_root) / folder / seq).is_dir():
                    continue
            seq_paths.append(f"{folder}/{seq}.npz")
    return seq_paths


def split_sequences(
    seq_paths: list[str],
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seed: int = 2026,
) -> tuple[list[str], list[str], list[str]]:
    """Sequence-level random split into train / val / test."""
    rng = random.Random(seed)
    paths = list(seq_paths)
    rng.shuffle(paths)
    n = len(paths)
    n_val  = max(1, int(n * val_ratio))
    n_test = max(1, int(n * test_ratio))
    test_paths  = paths[:n_test]
    val_paths   = paths[n_test: n_test + n_val]
    train_paths = paths[n_test + n_val:]
    return train_paths, val_paths, test_paths


def get_splits(
    overview_path: str,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seed: int = 2026,
    **filter_kwargs,
) -> tuple[list[str], list[str], list[str]]:
    """Filter sequences then split. Convenience wrapper."""
    seq_paths = get_seq_paths(overview_path, **filter_kwargs)
    return split_sequences(seq_paths, val_ratio=val_ratio, test_ratio=test_ratio, seed=seed)


# ── COLLATE ───────────────────────────────────────────────────────────────────

def collate_fn(batch: list[dict]) -> dict:
    """Stack tensors; pass metadata as lists."""
    out: dict = {}
    for key in batch[0]:
        vals = [item[key] for item in batch]
        if isinstance(vals[0], torch.Tensor):
            out[key] = torch.stack(vals)
        else:
            out[key] = vals
    return out


# ── DATASET ───────────────────────────────────────────────────────────────────

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
                     batch_size=16, shuffle=True, num_workers=4, prefetch_factor=2):
    dataset = BedlamFrameDataset(seq_paths=seq_paths, data_root=data_root,
                                 transform=transform, depth_required=depth_required)
    return DataLoader(
        dataset, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers,
        collate_fn=collate_fn, pin_memory=torch.cuda.is_available(),
        persistent_workers=False,
        prefetch_factor=(prefetch_factor if num_workers > 0 else None),
        multiprocessing_context=("spawn" if num_workers > 0 else None),
    )


# ── WEIGHT LOADING UTILITY ────────────────────────────────────────────────────

def _interp_pos_embed(
    pos_embed: torch.Tensor,
    tgt_h: int,
    tgt_w: int,
    has_cls: bool = True,
) -> torch.Tensor:
    """Bicubic-interpolate a 2D positional embedding to a new grid size.

    Args:
        pos_embed: ``(1, N, D)`` — source positional embedding.
        tgt_h, tgt_w: Target grid dimensions.
        has_cls: Whether the first token is a CLS token to be stripped.

    Returns:
        ``(1, tgt_h * tgt_w, D)``
    """
    if has_cls:
        pos_embed = pos_embed[:, 1:, :]
    _, N, D = pos_embed.shape
    src_h = src_w = int(N ** 0.5)
    assert src_h * src_w == N, f"Source pos_embed is not square: N={N}"
    grid = pos_embed.reshape(1, src_h, src_w, D).permute(0, 3, 1, 2).float()
    grid = F.interpolate(grid, size=(tgt_h, tgt_w), mode="bicubic", align_corners=False)
    return grid.permute(0, 2, 3, 1).reshape(1, tgt_h * tgt_w, D)


# ── LOGGING ───────────────────────────────────────────────────────────────────

_CSV_FIELDNAMES = [
    "epoch", "lr_backbone", "lr_head",
    "train_loss", "train_loss_pose",
    "train_mpjpe_body", "train_pelvis_err", "train_mpjpe_weighted",
    "val_loss", "val_loss_pose",
    "val_mpjpe_body", "val_pelvis_err", "val_mpjpe_weighted",
    "epoch_time",
]


class Logger:
    """Writes per-epoch metrics to a CSV file."""

    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self._file = open(csv_path, "w", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=_CSV_FIELDNAMES,
                                      extrasaction="ignore")
        self._writer.writeheader()
        self._file.flush()

    def log(self, row: dict):
        self._writer.writerow(row)
        self._file.flush()

    def close(self):
        self._file.close()


_ITER_CSV_FIELDNAMES = [
    "epoch", "iter",
    "loss", "loss_pose", "loss_depth", "loss_uv",
    "mpjpe_body", "pelvis_err", "mpjpe_weighted",
]


class IterLogger:
    """Writes per-iteration training metrics to a CSV file."""

    def __init__(self, csv_path: str):
        self._file = open(csv_path, "w", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=_ITER_CSV_FIELDNAMES,
                                      extrasaction="ignore")
        self._writer.writeheader()
        self._file.flush()

    def log(self, row: dict):
        self._writer.writerow(row)
        self._file.flush()

    def close(self):
        self._file.close()


# ── VISUALIZATION ─────────────────────────────────────────────────────────────

_RGB_MEAN_T  = torch.tensor(RGB_MEAN, dtype=torch.float32).view(3, 1, 1)
_RGB_STD_T   = torch.tensor(RGB_STD,  dtype=torch.float32).view(3, 1, 1)
_VIS_FRAMES  = 16
_PERSON_COLORS = [
    (0,   255, 0),    # green
    (255, 128, 0),    # orange
    (0,   128, 255),  # blue
    (255,   0, 255),  # magenta
    (0,   255, 255),  # cyan
]


def draw_pose_frame(
    rgb_chw: np.ndarray,
    joints: np.ndarray,
    K: np.ndarray,
    pelvis_abs: np.ndarray | None = None,
    color: tuple[int, int, int] = (0, 255, 0),
) -> np.ndarray:
    """Draw joints + skeleton on one RGB frame. Returns (3, H, W) uint8."""
    if pelvis_abs is not None:
        joints = joints + pelvis_abs[np.newaxis, :]

    img = np.ascontiguousarray(rgb_chw.transpose(1, 2, 0)[:, :, ::-1])  # HWC BGR
    H, W = img.shape[:2]

    X, Y, Z = joints[:, 0], joints[:, 1], joints[:, 2]
    valid = X > 0.01
    with np.errstate(divide="ignore", invalid="ignore"):
        u = np.where(valid, K[0, 0] * (-Y / X) + K[0, 2], -1.0)
        v = np.where(valid, K[1, 1] * (-Z / X) + K[1, 2], -1.0)

    for a, b in SMPLX_SKELETON:
        if valid[a] and valid[b]:
            cv2.line(img,
                     (int(round(u[a])), int(round(v[a]))),
                     (int(round(u[b])), int(round(v[b]))),
                     color, 2, cv2.LINE_AA)

    for j in range(NUM_JOINTS):
        if valid[j]:
            pt = (int(round(u[j])), int(round(v[j])))
            if 0 <= pt[0] < W and 0 <= pt[1] < H:
                cv2.circle(img, pt, 3, color, -1, cv2.LINE_AA)

    return img[:, :, ::-1].transpose(2, 0, 1)  # CHW RGB uint8


def build_val_video(
    rgb_frames: list[np.ndarray],
    pred_frames: list[np.ndarray],
    K_frames: list[np.ndarray],
    pelvis_frames: list[np.ndarray | None] | None = None,
) -> np.ndarray:
    """Return (1, T, 3, H, W) uint8 for writer.add_video()."""
    if pelvis_frames is None:
        pelvis_frames = [None] * len(rgb_frames)
    frames = [draw_pose_frame(r, p, k, pelvis_abs=pa)
              for r, p, k, pa in zip(rgb_frames, pred_frames, K_frames, pelvis_frames)]
    return np.stack(frames, axis=0)[np.newaxis]


def select_vis_indices(
    dataset,
    n_rotate_true: int = 1,
    n_rotate_false: int = 1,
    n_multi_person: int = 1,
) -> list[int]:
    """Return flat indices for a structured sample of visualization sequences."""
    true_indices: list[int] = []
    false_indices: list[int] = []
    multi_indices: list[int] = []
    seen: set = set()
    label_meta: dict = {}

    for i, (label_path, body_idx, _frame_idx) in enumerate(dataset.index):
        key = (label_path, body_idx)
        if key in seen:
            continue
        if (len(true_indices) >= n_rotate_true and len(false_indices) >= n_rotate_false
                and len(multi_indices) >= n_multi_person):
            break
        if label_path not in label_meta:
            try:
                with np.load(label_path, allow_pickle=True) as f:
                    label_meta[label_path] = (bool(f["rotate_flag"]),
                                              int(f["joints_cam"].shape[0]))
            except Exception:
                label_meta[label_path] = (False, 1)

        rotate_flag, n_body = label_meta[label_path]

        if n_body > 1 and len(multi_indices) < n_multi_person:
            multi_indices.append(i)
            seen.add(key)
        elif rotate_flag and len(true_indices) < n_rotate_true:
            true_indices.append(i)
            seen.add(key)
        elif not rotate_flag and len(false_indices) < n_rotate_false:
            false_indices.append(i)
            seen.add(key)

    return true_indices + false_indices + multi_indices


def sample_random_vis_index(dataset) -> int:
    """Return flat index of the first frame from a randomly selected sequence."""
    seq_first: dict[tuple, int] = {}
    for i, (label_path, body_idx, _frame_idx) in enumerate(dataset.index):
        key = (label_path, body_idx)
        if key not in seq_first:
            seq_first[key] = i
    return seq_first[random.choice(list(seq_first.keys()))]


def recover_pelvis_from_pred(
    pred_depth: float,
    pred_uv: np.ndarray,
    K: np.ndarray,
    crop_hw: tuple[int, int] = (640, 384),
) -> np.ndarray:
    """Recover absolute pelvis XYZ from predicted depth and UV (normalized [-1,1])."""
    crop_h, crop_w = crop_hw
    u_crop = (pred_uv[0] + 1.0) / 2.0 * crop_w
    v_crop = (pred_uv[1] + 1.0) / 2.0 * crop_h
    X = float(pred_depth)
    fx, cx = float(K[0, 0]), float(K[0, 2])
    fy, cy = float(K[1, 1]), float(K[1, 2])
    Y = -(u_crop - cx) * X / fx
    Z = -(v_crop - cy) * X / fy
    return np.array([X, Y, Z], dtype=np.float32)


def visualize_fixed_samples(
    model,
    dataset,
    indices: list[int],
    device: torch.device,
    val_tf,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Render _VIS_FRAMES-frame pose-overlay videos for each starting index.

    Returns a list of ``(vid_gt, vid_pred)`` pairs, one per starting index.
    Each video is ``(1, T, 3, H, W)`` uint8 ready for ``writer.add_video()``.
    """
    orig_transform = dataset.transform
    dataset.transform = val_tf
    result = []
    try:
        for start_idx in indices:
            label_path, body_idx, _ = dataset.index[start_idx]

            try:
                with np.load(label_path, allow_pickle=True) as f:
                    n_body = int(f["joints_cam"].shape[0])
            except Exception:
                n_body = 1
            is_multi = n_body > 1

            if is_multi:
                frame_body_map: dict[int, dict[int, int]] = {}
                for j, (lp, bi, fi_) in enumerate(dataset.index):
                    if lp == label_path:
                        frame_body_map.setdefault(fi_, {})[bi] = j

            rgb_frames, pred_frames, K_frames = [], [], []
            orig_rgb_frames: list[np.ndarray] = []
            orig_K_frames: list[np.ndarray] = []
            gt_pelvis_frames: list[np.ndarray | None] = []
            multi_pred_per_frame: list[list[tuple]] = []

            i = start_idx
            while len(rgb_frames) < _VIS_FRAMES and i < len(dataset.index):
                lp, bi, fi = dataset.index[i]
                if lp != label_path or bi != body_idx:
                    break
                sample = dataset[i]
                rgb_t   = sample["rgb"]
                depth_t = sample["depth"]
                K_t     = sample["intrinsic"]

                x = torch.cat([rgb_t.unsqueeze(0), depth_t.unsqueeze(0)], dim=1).to(device)
                with torch.no_grad():
                    out = model(x)
                    pred_joints_np = out["joints"][0].float().cpu().numpy()
                    pd_val = out["pelvis_depth"][0, 0].float().cpu().item()
                    pu_val = out["pelvis_uv"][0].float().cpu().numpy()
                del x, out

                rgb_u8 = ((rgb_t * _RGB_STD_T + _RGB_MEAN_T).clamp(0, 1) * 255).byte().numpy()
                K_np   = K_t.numpy() if isinstance(K_t, torch.Tensor) else K_t
                rgb_frames.append(rgb_u8)
                pred_frames.append(pred_joints_np)
                K_frames.append(K_np)

                cached = dataset._label_cache[lp]
                orig_rgb_hwc = dataset._read_frame(
                    cached["folder_name"], cached["seq_name"], fi, lp
                )
                orig_rgb_frames.append(orig_rgb_hwc.transpose(2, 0, 1))
                orig_K_frames.append(cached["intrinsic_matrix"])

                if "pelvis_abs" in sample:
                    pa = sample["pelvis_abs"]
                    gt_pelvis_frames.append(pa.numpy() if isinstance(pa, torch.Tensor) else pa)
                else:
                    gt_pelvis_frames.append(None)

                if is_multi:
                    frame_bodies: list[tuple] = []
                    for bk in range(n_body):
                        idx_bk = frame_body_map.get(fi, {}).get(bk)
                        if idx_bk is None:
                            continue
                        sample_bk = dataset[idx_bk]
                        K_bk = sample_bk["intrinsic"]
                        K_bk = K_bk.numpy() if isinstance(K_bk, torch.Tensor) else K_bk
                        x_bk = torch.cat([
                            sample_bk["rgb"].unsqueeze(0),
                            sample_bk["depth"].unsqueeze(0),
                        ], dim=1).to(device)
                        with torch.no_grad():
                            out_bk = model(x_bk)
                        joints_bk  = out_bk["joints"][0].float().cpu().numpy()
                        pelvis_bk  = recover_pelvis_from_pred(
                            out_bk["pelvis_depth"][0, 0].float().cpu().item(),
                            out_bk["pelvis_uv"][0].float().cpu().numpy(),
                            K_bk,
                        )
                        del x_bk, out_bk
                        frame_bodies.append(
                            (joints_bk, pelvis_bk, _PERSON_COLORS[bk % len(_PERSON_COLORS)])
                        )
                    multi_pred_per_frame.append(frame_bodies)
                else:
                    pelvis_pred = recover_pelvis_from_pred(pd_val, pu_val, K_np)
                    multi_pred_per_frame.append([
                        (pred_joints_np, pelvis_pred, _PERSON_COLORS[0])
                    ])

                i += 1

            if rgb_frames:
                vid_gt = build_val_video(rgb_frames, pred_frames, K_frames, gt_pelvis_frames)

                pred_frames_out = []
                for orig_rgb, frame_bodies, orig_K in zip(
                    orig_rgb_frames, multi_pred_per_frame, orig_K_frames
                ):
                    img = orig_rgb
                    for joints, pelvis, color in frame_bodies:
                        img = draw_pose_frame(img, joints, orig_K, pelvis_abs=pelvis, color=color)
                    pred_frames_out.append(img)
                vid_pred = np.stack(pred_frames_out)[np.newaxis]

                result.append((vid_gt, vid_pred))
    finally:
        dataset.transform = orig_transform

    return result


# ── CHECKPOINT HELPERS ────────────────────────────────────────────────────────

def save_checkpoint(state: dict, path: str):
    torch.save(state, path)
    print(f"  Saved checkpoint → {path}")


def load_checkpoint(model, optimizer, scaler, path: str, device: torch.device):
    ckpt = torch.load(path, map_location=device, weights_only=False)
    ckpt_sd = ckpt["model"]
    try:
        model.load_state_dict(ckpt_sd)
    except RuntimeError:
        model.load_state_dict(ckpt_sd, strict=False)
        print("  Warning: loaded checkpoint with strict=False (head structure changed)")
    optimizer.load_state_dict(ckpt["optimizer"])
    scaler.load_state_dict(ckpt["scaler"])
    start_epoch = ckpt["epoch"] + 1
    best_mpjpe  = ckpt.get("best_mpjpe", float("inf"))
    print(f"  Resumed from epoch {ckpt['epoch']}  (best MPJPE body={best_mpjpe:.1f}mm)")
    return start_epoch, best_mpjpe


# ── METRICS & LOSS ────────────────────────────────────────────────────────────

BODY_IDX = slice(0, 22)   # core kinematic joints
HAND_IDX = slice(24, 54)  # left + right hand joints


def mpjpe(pred: torch.Tensor, target: torch.Tensor,
          idx: slice | None = None) -> torch.Tensor:
    """Mean per-joint position error in millimetres."""
    if idx is not None:
        pred, target = pred[:, idx], target[:, idx]
    return (pred - target).norm(dim=-1).mean() * 1000.0


def pose_loss(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Smooth L1 (beta=0.05 m): L2 below 5 cm, L1 above."""
    return nn.functional.smooth_l1_loss(pred, target, beta=0.05)


def recover_pelvis_3d(
    pelvis_depth: torch.Tensor,
    pelvis_uv: torch.Tensor,
    K: torch.Tensor,
    crop_h: int,
    crop_w: int,
) -> torch.Tensor:
    """Unproject predicted (depth, uv) → absolute 3D pelvis (B, 3) in metres.

    BEDLAM2 convention: X=forward (depth), Y=left, Z=up.
    Inverse projection: Y = -(u_px - cx)*X/fx,  Z = -(v_px - cy)*X/fy
    """
    fx = K[:, 0, 0]; fy = K[:, 1, 1]
    cx = K[:, 0, 2]; cy = K[:, 1, 2]
    X    = pelvis_depth[:, 0]
    u_px = (pelvis_uv[:, 0] + 1.0) / 2.0 * crop_w
    v_px = (pelvis_uv[:, 1] + 1.0) / 2.0 * crop_h
    Y = -(u_px - cx) * X / fx
    Z = -(v_px - cy) * X / fy
    return torch.stack([X, Y, Z], dim=-1)   # (B, 3)


def pelvis_abs_error(
    pred_depth: torch.Tensor,
    pred_uv: torch.Tensor,
    gt_pelvis_abs: torch.Tensor,
    K: torch.Tensor,
    crop_h: int,
    crop_w: int,
) -> torch.Tensor:
    """Absolute pelvis position error in mm."""
    pred_pelvis = recover_pelvis_3d(pred_depth, pred_uv, K, crop_h, crop_w)
    return (pred_pelvis - gt_pelvis_abs).norm(dim=-1).mean() * 1000.0

@torch.no_grad()
def validate(model, loader, device, args) -> dict:
    model.eval()
    total = {k: 0.0 for k in ("loss", "pose", "body", "pelvis_err", "weighted")}
    n = 0
    pbar = tqdm(loader, total=args.max_batches or len(loader),
                desc="         [val] ", leave=True, dynamic_ncols=True)

    for batch in pbar:
        rgb           = batch["rgb"].to(device, non_blocking=True)
        depth         = batch["depth"].to(device, non_blocking=True)
        joints        = batch["joints"].to(device, non_blocking=True)
        gt_pelvis_abs = batch["pelvis_abs"].to(device, non_blocking=True)
        gt_pd         = batch["pelvis_depth"].to(device, non_blocking=True)
        gt_uv         = batch["pelvis_uv"].to(device, non_blocking=True)
        K             = batch["intrinsic"].to(device, non_blocking=True)
        x = torch.cat([rgb, depth], dim=1)

        with torch.amp.autocast("cuda", enabled=args.amp):
            out = model(x)

        pf     = out["joints"].float()
        l_pose = pose_loss(pf[:, BODY_IDX], joints[:, BODY_IDX]).item()
        body   = mpjpe(pf, joints, BODY_IDX).item()
        pe     = pelvis_abs_error(out["pelvis_depth"].float(), out["pelvis_uv"].float(),
                                  gt_pelvis_abs, K, args.img_h, args.img_w).item()

        total["loss"]       += l_pose
        total["pose"]       += l_pose
        total["body"]       += body
        total["pelvis_err"] += pe
        total["weighted"]   += 0.67 * body + 0.33 * pe
        del x, out, pf
        n += 1
        pbar.set_postfix(body=f"{total['body']/n:.1f}mm",
                         pelvis=f"{total['pelvis_err']/n:.1f}mm",
                         w=f"{total['weighted']/n:.1f}mm")
        if args.max_batches > 0 and n >= args.max_batches:
            break

    pbar.close()
    n = max(1, n)
    return {
        "val_loss":              total["loss"] / n,
        "val_loss_pose":         total["pose"] / n,
        "val_mpjpe_body":        total["body"] / n,
        "val_pelvis_err":        total["pelvis_err"] / n,
        "val_mpjpe_weighted":    total["weighted"] / n,
    }


