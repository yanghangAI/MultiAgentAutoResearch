"""Data transforms for SapiensPose3D.

Augmentation entry point: modify build_train_transform to add augmentations.
build_val_transform should remain deterministic.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
import torch

from infra import PELVIS_IDX, RGB_MEAN, RGB_STD, DEPTH_MAX_METERS


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
