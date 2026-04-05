"""Training entry point for SapiensPose3D — idea004/design002.

Constant Decay LLRD (gamma=0.90, unfreeze_epoch=5):
- Per-block learning rates: lr_i = base_lr_backbone * gamma^(23-i)
- Patch+pos embedding: lr_embed = base_lr_backbone * gamma^24
- Head lr: args.lr_head (unchanged)
- Epochs 0-4: blocks 0-11 + embeddings frozen (excluded from optimizer)
- Epoch 5+: all blocks unfrozen, optimizer rebuilt with 26 param groups
"""

from __future__ import annotations

import math
import os
import random
import resource
import sys
import time
from pathlib import Path

# ── Raise the open-file-descriptor limit ─────────────────────────────────────
_soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (min(65536, _hard), _hard))

# ── Ensure sibling modules (model.py, transforms.py) are importable ──────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import numpy as np
import torch
import torch.nn as nn
from torch.amp import GradScaler
from tqdm import tqdm

from infra import (
    NUM_JOINTS,
    get_splits, build_dataloader,
    Logger, IterLogger,
    save_checkpoint, load_checkpoint,
    validate, pose_loss, mpjpe, pelvis_abs_error, BODY_IDX,
)
from model import SapiensPose3D
from transforms import build_train_transform, build_val_transform
from config import get_config


# ── LLRD CONSTANTS ────────────────────────────────────────────────────────────
NUM_BLOCKS      = 24


def _block_lr(block_idx: int, base_lr: float, gamma: float) -> float:
    """LLRD lr for block i: base_lr * gamma^(23-i)."""
    return base_lr * (gamma ** (NUM_BLOCKS - 1 - block_idx))


def _embed_lr(base_lr: float, gamma: float) -> float:
    """LR for patch+pos embedding: base_lr * gamma^24."""
    return base_lr * (gamma ** NUM_BLOCKS)


def _worker_init_fn(worker_id: int):
    """Deterministic DataLoader workers."""
    seed = 2026 + worker_id
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


# ── OPTIMIZER BUILDERS ────────────────────────────────────────────────────────

def _build_optimizer_frozen(model, weight_decay: float, base_lr: float, gamma: float, lr_head: float):
    """
    Epochs 0-4: blocks 0-11 + embeddings frozen.
    Active param groups: blocks 12-23 (12 groups) + head (1 group) = 13 total.
    """
    vit = model.backbone.vit

    # Freeze blocks 0-11 and embeddings
    for p in vit.patch_embed.parameters():
        p.requires_grad = False
    vit.pos_embed.requires_grad = False
    for i in range(12):
        for p in vit.layers[i].parameters():
            p.requires_grad = False

    # Ensure blocks 12-23 and head are active
    for i in range(12, NUM_BLOCKS):
        for p in vit.layers[i].parameters():
            p.requires_grad = True
    for p in model.head.parameters():
        p.requires_grad = True

    param_groups = []
    for i in range(12, NUM_BLOCKS):
        param_groups.append({
            "params": list(vit.layers[i].parameters()),
            "lr": _block_lr(i, base_lr, gamma),
            "initial_lr": _block_lr(i, base_lr, gamma),
        })
    param_groups.append({
        "params": list(model.head.parameters()),
        "lr": lr_head,
        "initial_lr": lr_head,
    })

    return torch.optim.AdamW(param_groups, weight_decay=weight_decay)


def _build_optimizer_full(model, weight_decay: float, base_lr: float, gamma: float, lr_head: float):
    """
    Epochs 5+: all blocks unfrozen.
    Param groups: embed (1) + blocks 0-23 (24) + head (1) = 26 total.
    """
    vit = model.backbone.vit

    # Unfreeze everything
    for p in vit.patch_embed.parameters():
        p.requires_grad = True
    vit.pos_embed.requires_grad = True
    for i in range(NUM_BLOCKS):
        for p in vit.layers[i].parameters():
            p.requires_grad = True
    for p in model.head.parameters():
        p.requires_grad = True

    lr_emb = _embed_lr(base_lr, gamma)
    embed_params = list(vit.patch_embed.parameters()) + [vit.pos_embed]
    param_groups = [{
        "params": embed_params,
        "lr": lr_emb,
        "initial_lr": lr_emb,
    }]
    for i in range(NUM_BLOCKS):
        param_groups.append({
            "params": list(vit.layers[i].parameters()),
            "lr": _block_lr(i, base_lr, gamma),
            "initial_lr": _block_lr(i, base_lr, gamma),
        })
    param_groups.append({
        "params": list(model.head.parameters()),
        "lr": lr_head,
        "initial_lr": lr_head,
    })

    return torch.optim.AdamW(param_groups, weight_decay=weight_decay)


# ── LR SCHEDULE ───────────────────────────────────────────────────────────────

def get_lr_scale(epoch: int, total_epochs: int, warmup_epochs: int) -> float:
    """Linear warmup then cosine decay."""
    if epoch < warmup_epochs:
        return (epoch + 1) / warmup_epochs
    progress = (epoch - warmup_epochs) / max(1, total_epochs - warmup_epochs)
    return 0.5 * (1.0 + math.cos(math.pi * progress))


# ── TRAIN LOOP ────────────────────────────────────────────────────────────────

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


def main():
    # ── Deterministic seed ────────────────────────────────────────────────────
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
                                    num_workers=args.num_workers)
    val_loader   = build_dataloader(val_seqs,   args.data_root, val_tf,
                                    batch_size=args.batch_size, shuffle=False,
                                    num_workers=args.num_workers)
    print(f"  Frames  — train: {len(train_loader.dataset)}, val: {len(val_loader.dataset)}")

    # Model
    print(f"\nBuilding {args.arch} ...")
    model = SapiensPose3D(
        arch=args.arch, img_size=(args.img_h, args.img_w), num_joints=NUM_JOINTS,
        head_hidden=args.head_hidden, head_num_heads=args.head_num_heads,
        head_num_layers=args.head_num_layers, head_dropout=args.head_dropout,
        drop_path_rate=args.drop_path,
    ).to(device)
    if args.pretrain and not args.resume:
        model.load_pretrained(args.pretrain)
    print(f"  Parameters: {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M")

    # ── LLRD Optimizer (frozen lower half for epochs 0-4) ────────────────────
    print(f"\n[LLRD] Building initial optimizer: blocks 12-23 + head active, blocks 0-11 + embed frozen.")
    optimizer = _build_optimizer_frozen(
        model,
        weight_decay=args.weight_decay,
        base_lr=args.lr_backbone,
        gamma=args.gamma,
        lr_head=args.lr_head,
    )
    print(f"  Param groups: {len(optimizer.param_groups)}  (expect 13)")
    scaler = GradScaler("cuda", enabled=args.amp)

    # Resume
    start_epoch = 0
    best_mpjpe  = float("inf")
    if args.resume:
        start_epoch, best_mpjpe = load_checkpoint(model, optimizer, scaler, args.resume, device)

    logger      = Logger(str(out_dir / "metrics.csv"))
    iter_logger = IterLogger(str(out_dir / "iter_metrics.csv"))

    print(f"\nStarting training for {args.epochs} epochs ...\n")
    patience_counter = 0

    for epoch in range(start_epoch, args.epochs):
        # ── Progressive unfreezing at epoch 5 ────────────────────────────────
        if epoch == args.unfreeze_epoch:
            print(f"\n[LLRD] Epoch {epoch}: unfreezing blocks 0-11 + embeddings. Rebuilding optimizer.")
            optimizer = _build_optimizer_full(
                model,
                weight_decay=args.weight_decay,
                base_lr=args.lr_backbone,
                gamma=args.gamma,
                lr_head=args.lr_head,
            )
            print(f"  Param groups: {len(optimizer.param_groups)}  (expect 26)")

        # ── Apply LR scale ────────────────────────────────────────────────────
        scale = get_lr_scale(epoch, args.epochs, args.warmup_epochs)
        for g in optimizer.param_groups:
            g["lr"] = g["initial_lr"] * scale

        # Report deepest block LR (block 23) as lr_backbone
        # In frozen phase: block 23 is group index 11 (blocks 12..23 = indices 0..11)
        # In full phase: block 23 is group index 24 (embed=0, blocks 0-23=1-24, head=25)
        if epoch < args.unfreeze_epoch:
            # groups: [block12, block13, ..., block23, head] -> block23 is index 11
            lr_bb = optimizer.param_groups[11]["lr"]
            lr_hd = optimizer.param_groups[12]["lr"]
        else:
            # groups: [embed, block0, ..., block23, head] -> block23 is index 24
            lr_bb = optimizer.param_groups[24]["lr"]
            lr_hd = optimizer.param_groups[25]["lr"]

        print(f"Epoch {epoch+1}/{args.epochs}  lr_backbone(block23)={lr_bb:.2e}  lr_head={lr_hd:.2e}"
              f"  scale={scale:.4f}  n_groups={len(optimizer.param_groups)}")

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
    # Print final val body MPJPE as a single float to stdout
    if val_m:
        print(val_m["val_mpjpe_body"])


if __name__ == "__main__":
    main()
