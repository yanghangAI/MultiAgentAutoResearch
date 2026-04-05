# Experiment Designer Memory

## Idea 005 Current State (Depth-Aware Positional Embeddings) — COMPLETE 2026-04-03
- 3 designs requested, all APPROVED by Architect on 2026-04-03.
- design001 (discretized_depth_pe): Decomposed row+col+depth bucket PE. row_emb (40,1024) + col_emb (24,1024) init from pretrained pos_embed mean-projection; depth_emb (16,1024) zero-init. vit.pos_embed → frozen zero buffer. depth_bucket_pe params at lr=1e-4.
- design002 (relative_depth_bias): Additive depth bias to Pose3DHead cross-attention. Linear(1,70) zero-init; bias shape (B*nH,70,960) added as attn_mask. Manual decoder loop replaces self.decoder(). DepthAttentionBias in head group at lr=1e-4.
- design003 (depth_conditioned_pe): 3-layer MLP (3→128→256→1024), Xavier(gain=0.01) near-zero init. Adds residual PE correction on top of pretrained pos_embed. bypass vit.forward(), manually call patch_embed→pe_base+pe_correction→layers→norm. depth_cond_pe at lr=1e-4, backbone (incl. pos_embed) at lr=1e-5.
- Key implementation warning for design003: Builder must inspect mmpretrain ViT attribute names before coding.

## Idea 003 Current State (updated 2026-04-02)
- Design 001 (Homoscedastic Uncertainty Loss Weighting): APPROVED by Architect.
  - Three learnable scalars: `model.log_var_pose`, `model.log_var_depth`, `model.log_var_uv` (nn.Parameter, init=0.0)
  - Loss: `exp(-s)*L + s` per task (Kendall et al. 2018)
  - Third optimizer param group at lr_head=1e-4 for the three log_var params
  - NOTE from Architect: keep unused `lambda_depth`/`lambda_uv` in get_config() rather than removing them
- Design 002 (Linear Warmup for Depth Loss): APPROVED by Architect.
  - `depth_start_weight=0.0`, `depth_target_weight=0.1`, `depth_warmup_epochs=5`
  - Schedule: `target * (epoch / warmup_epochs)` for epoch < warmup_epochs, else target
  - Function name: `get_depth_weight(epoch, start_weight, target_weight, warmup_epochs)`
  - `train_one_epoch` gains `depth_weight: float = 0.1` parameter
  - LR cosine schedule and depth weight schedule are fully orthogonal (no coupling)
  - `lambda_uv=0.2` fixed throughout; `lambda_depth` arg removed from config
- Workflow complete (2 designs requested, both APPROVED).

## Idea 002 Current State (Kinematic Attention Masking)
- All 3 designs originally REJECTED for lacking implementation detail.
- Revised all 3 designs on 2026-04-02 with full implementation detail:
  - design001 (Baseline Dense): Added attention_method plumbing, confirmed optimizer matches baseline.py exactly (lr_backbone=1e-5, lr_head=1e-4, weight_decay=0.03), documented HOP_DIST as shared module-level constant.
  - design002 (Soft Kinematic Mask): Added exact formula (tgt_mask[i,j] = d(i,j)*log(0.5)), confirmed self-attention sub-layer via tgt_mask, documented no cutoff (global bias), confirmed no NaN risk (all finite).
  - design003 (Hard Kinematic Mask): Added exact mask values (0.0 / -inf), NaN guard for fully-masked rows, confirmed self-attention sub-layer, buffer registration, shape (70,70) broadcasting, no warmup schedule.
- Awaiting Architect re-review of all 3 revised designs.

## Key baseline.py Facts
- Optimizer: AdamW with lr_backbone=1e-5, lr_head=1e-4, weight_decay=0.03 (NOT lr=5e-4 as initially mistaken)
- Pose3DHead.forward: self.decoder(queries, memory) — no tgt_mask argument in baseline
- SMPLX_SKELETON in infra.py already uses remapped 0..69 indices (via _ORIG_TO_NEW)
- NUM_JOINTS = 70; active joints include body (0-21), eyes (23-24), hands (25-54), surface landmarks (60-75 in orig, remapped)
- BATCH_SIZE=4, ACCUM_STEPS=8 are constants in infra.py (do not override)
- Backbone outputs (B, 1024, 40, 24); input_proj in head: Linear(1024→256)
- train loop: x = torch.cat([rgb, depth], dim=1) → (B, 4, 640, 384)

## Idea 001 Current State (RGB-D Modality Fusion Strategy)
- 3 designs needed: early_4ch, mid_fusion, late_cross_attention
- Design 001 (early_4ch): APPROVED — logged to runs/idea001/design_overview.csv
  - Code review (2026-04-02): APPROVED — train.py matches design.md exactly; status should be set to 'Implemented' in design_overview.csv
- Design 002 (mid_fusion): APPROVED — logged to runs/idea001/design_overview.csv
  - Injection after block 11 (of 24), additive bias via DepthProjector (Conv2d zeros-init)
  - RGB patch embed unchanged (3-ch); standard pretrained weights load cleanly
  - 3 optimizer param groups: backbone lr=1e-5, depth_proj lr=1e-4, head lr=1e-4
- Design 003 (late_cross_attention): APPROVED (code review 2026-04-02)
  - Full ViT runs on RGB only (3-ch, unchanged), depth introduced after ViT via cross-attention
  - DepthTokenizer: Conv2d(1→64) zeros-init → (B,960,64) depth tokens
  - DepthCrossAttention: RGB tokens (1024-dim) as Q, depth tokens (64-dim) as K/V
  - qk_dim=256, num_heads=8, head_dim=32; out_proj zeros-init for clean warm-start
  - Depth adapter ~9M params; total ~317M
  - 3 optimizer param groups: backbone lr=1e-5, depth_adapter lr=1e-4, head lr=1e-4
  - train.py uses F.scaled_dot_product_attention (permitted by spec note)
