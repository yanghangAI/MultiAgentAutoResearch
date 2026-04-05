# ProxyEnvironmentBuilder Memory

## Current Task
- Idea: idea004 (Layer-Wise Learning Rate Decay)
- design001 (Constant Decay LLRD, gamma=0.95, unfreeze_epoch=5): IMPLEMENTED, TEST PASSED.

## idea004/design001 Status
- Path: /work/pi_nwycoff_umass_edu/hang/auto/runs/idea004/design001/code/train.py
- Test job: 54988411, PASSED
- Final val body MPJPE: 530.07mm (2-epoch test run)
- Test output: /work/pi_nwycoff_umass_edu/hang/auto/runs/idea004/design001/test_output/
- Key implementation details:
  1. LLRD: lr_i = 1e-4 * 0.95^(23-i) for block i; embed lr = 1e-4 * 0.95^24; head lr = 1e-4
  2. _build_optimizer_frozen(): epochs 0-4, blocks 0-11 + patch_embed + pos_embed frozen
     (requires_grad=False), param groups = blocks 12-23 (12) + head (1) = 13 total
  3. _build_optimizer_full(): epoch 5+, all unfrozen, param groups = embed(1) + blocks 0-23(24) + head(1) = 26 total
  4. At epoch == UNFREEZE_EPOCH (5): rebuild optimizer before LR scale is applied
  5. lr_backbone reported in metrics.csv = deepest block (block 23) LR
     - Frozen phase: optimizer.param_groups[11] (block 23 = index 11 in 0-based block 12..23)
     - Full phase: optimizer.param_groups[24] (block 23 = index 24 in [embed, block0..23, head])
  6. Random seed 2026 at start of main(); PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
  7. build_dataloader does NOT accept worker_init_fn — omit it (num_workers=0 in test anyway)
  8. No weight saving; final val body MPJPE printed as single float at end of main()

## idea001 (Previous Work)
- Idea: idea001 (RGB-D Modality Fusion Strategy)
- design001 (early_4ch): IMPLEMENTED, TEST PASSED. APPROVED by Designer, marked Implemented.
- design002 (mid_fusion): IMPLEMENTED, TEST PASSED. Awaiting Designer code review.
- design003 (late_cross_attention): IMPLEMENTED, TEST PASSED. Awaiting Designer code review.

## idea001/design003 Status
- Path: /work/pi_nwycoff_umass_edu/hang/auto/runs/idea001/design003/train.py
- Test job: 54955332, PASSED
- Final val body MPJPE: 1480.5mm (2-epoch test run)
- Test output: /work/pi_nwycoff_umass_edu/hang/auto/runs/idea001/design003/test_output/
- Key implementation details:
  1. New `DepthTokenizer`: Conv2d(1→64, k=16, s=16, padding=2) + LayerNorm(64);
     weight/bias zero-initialized → depth tokens = 0 at epoch 0
  2. New `DepthCrossAttention`: single cross-attention block with pre-norm+residual;
     q_proj(1024→256) Xavier, k/v_proj(64→256) Xavier, out_proj(256→1024) zero-init;
     FFN: Linear(1024→4096) → GELU → Dropout → Linear(4096→1024) → Dropout; Xavier init
     Uses F.scaled_dot_product_attention (PyTorch 2.6, scale kwarg supported)
  3. New `SapiensBackboneLateFusion`: 3-ch ViT unchanged; manually iterates ViT layers
     with per-layer grad_ckpt (use_reentrant=False) to reduce peak VRAM;
     also uses grad_ckpt on depth_cross_attn to avoid 60MB FFN activation OOM
  4. VisionTransformer.forward returns tuple(outs); use vit_out[-1] for the featmap
     (discovered during debugging; fixed with manual ViT iteration in _run_vit_with_ckpt)
  5. Memory: ViT backbone alone fills ~5GB → 10.65GB at FFN without grad ckpt;
     with per-layer grad ckpt on ViT layers + depth_cross_attn: 2.40GB batch1 / 4.76GB batch2
  6. PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True set via os.environ.setdefault
  7. Optimizer: 3 groups — vit (lr=1e-5), depth_adapter (tokenizer+cross_attn, lr=1e-4), head (lr=1e-4)
  8. fusion_strategy = "late_cross_attention", output_dir = runs/idea001/design003

## idea001/design002 Status
- Path: /work/pi_nwycoff_umass_edu/hang/auto/runs/idea001/design002/train.py
- Test job: 54933311, PASSED
- Final val body MPJPE: 600.88mm (2-epoch test run)
- Test output: /work/pi_nwycoff_umass_edu/hang/auto/runs/idea001/design002/test_output/
- Key changes from design001/train.py:
  1. New `DepthProjector` module: Conv2d(1→1024, k=16, s=16, padding=2) + LayerNorm;
     weight/bias zero-initialized so epoch-0 = pure RGB
  2. New `SapiensBackboneMidFusion`: 3-channel ViT, manually iterates `vit.layers`,
     injects `depth_proj(depth)` additively before block 12 (INJECT_BEFORE = 12)
  3. `resize_pos_embed` imported from `mmpretrain.models.utils` for manual forward
  4. `SapiensPose3D.forward(x)` accepts concatenated (B,4,H,W) and splits internally
     → rgb = x[:, :3], depth = x[:, 3:] → keeps infra.validate compatible
  5. `load_sapiens_pretrained`: skips 4-ch expansion; loads 3-ch weights directly;
     skips backbone.depth_proj.* keys (zero-init intentional)
  6. Optimizer: 3 groups — vit (lr=1e-5), depth_proj (lr=1e-4), head (lr=1e-4)
  7. `fusion_strategy = "mid_fusion"`, `output_dir = runs/idea001/design002`
- GPU memory: 2.33GB epoch 1 / 4.64GB epoch 2 — fits 1080ti 11GB

## idea002 (Previous Work)
- Idea: idea002 (Kinematic Attention Masking)
- design001 (Baseline Dense Control): train.py IMPLEMENTED and TEST PASSED. Awaiting Experiment Designer approval before proceeding.
- design002 (Soft Kinematic Mask): IMPLEMENTED, TEST PASSED. Awaiting Experiment Designer review.
- design003 (Hard Kinematic Mask): IMPLEMENTED, TEST PASSED. Awaiting Experiment Designer review.

## design001 Status
- Path: /work/pi_nwycoff_umass_edu/hang/auto/runs/idea002/design001/train.py
- Test job: 54892104, PASSED
- Final val body MPJPE: 517.03mm
- Test output: /work/pi_nwycoff_umass_edu/hang/auto/runs/idea002/design001/test_output/
- Key changes from baseline.py:
  1. Added `HOP_DIST` module-level constant (BFS on SMPLX_SKELETON from infra.py)
  2. Pose3DHead accepts `attention_method: str` arg (default "dense")
  3. Pose3DHead.forward passes `tgt_mask=None` explicitly
  4. SapiensPose3D passes `attention_method="dense"` to head
  5. Added global seed 2026 at start of main()
  6. Added _worker_init_fn for deterministic DataLoader workers
  7. Prints FINAL_VAL_MPJPE_BODY as single float to stdout
  8. output_dir default updated to runs/idea002/design001

## design002 Status
- Path: /work/pi_nwycoff_umass_edu/hang/auto/runs/idea002/design002/train.py
- Test job: 54893737, PASSED
- Final val body MPJPE: 307.12mm
- Test output: /work/pi_nwycoff_umass_edu/hang/auto/runs/idea002/design002/test_output/
- Key changes from design001:
  1. Pose3DHead.__init__: when attention_method="soft_kinematic_mask", computes
     soft_bias = HOP_DIST.float() * math.log(0.5) and registers as buffer
  2. Pose3DHead.forward: if attention_method=="soft_kinematic_mask", calls
     self.decoder(queries, memory, tgt_mask=self.soft_bias)
  3. SapiensPose3D in main() instantiated with attention_method="soft_kinematic_mask"
  4. output_dir updated to runs/idea002/design002

## design003 Status
- Path: /work/pi_nwycoff_umass_edu/hang/auto/runs/idea002/design003/train.py
- Test job: 54894734, PASSED
- Final val body MPJPE: 297.41mm
- Test output: /work/pi_nwycoff_umass_edu/hang/auto/runs/idea002/design003/test_output/
- Key changes from design002:
  1. Pose3DHead.__init__: when attention_method="hard_kinematic_mask", computes
     hard_mask (70,70) float32: 0.0 where hop distance <= 2, -inf otherwise
     NaN guard: fully-masked rows (if any) set to dense (all True)
     Registered as self.register_buffer("hard_mask", hard_mask)
  2. Pose3DHead.forward: if attention_method=="hard_kinematic_mask", calls
     self.decoder(queries, memory, tgt_mask=self.hard_mask)
  3. SapiensPose3D in main() instantiated with attention_method="hard_kinematic_mask"
  4. output_dir updated to runs/idea002/design003
  5. No warmup or annealing; hard masking from epoch 0

## Key Infrastructure Notes
- baseline.py is at /work/pi_nwycoff_umass_edu/hang/auto/baseline.py
- infra.py exports: NUM_JOINTS, SMPLX_SKELETON, PELVIS_IDX, ACTIVE_JOINT_INDICES, etc.
- SMPLX_SKELETON uses remapped 0..69 indices (via _ORIG_TO_NEW)
- Test script: ./scripts/submit_test.sh — handles output_dir creation and overrides _Cfg.output_dir to <design_dir>/test_output
- Test job sets: epochs=2, max_train_seqs=2, max_val_seqs=1, num_workers=0
- CSV headers required:
  - iter_metrics.csv: epoch,iter,loss,loss_pose,loss_depth,loss_uv,mpjpe_body,pelvis_err,mpjpe_weighted
  - metrics.csv: epoch,lr_backbone,lr_head,train_loss,train_loss_pose,train_mpjpe_body,train_pelvis_err,train_mpjpe_weighted,val_loss,val_loss_pose,val_mpjpe_body,val_pelvis_err,val_mpjpe_weighted,epoch_time
- BODY_IDX = slice(0, 22) — body + pelvis joints only for MPJPE reporting
- GPU: 1080ti, 11GB VRAM — no FP16, amp=False. Batch 1 allocates ~2.3GB for design001
