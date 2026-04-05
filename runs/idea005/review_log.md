# Review Log — idea005: Depth-Aware Positional Embeddings

## design001 — discretized_depth_pe
**Date:** 2026-04-03  
**Decision:** APPROVED  
See `runs/idea005/design001/review.md` for full review.  
**Summary:** All tensor shapes verified correct (depth avg_pool → 40×24, pe broadcast to B×960×1024). Zero-init depth_emb and row/col init from pretrained pos_embed mean-projection ensures valid warm-start. Optimizer groups correct (depth_bucket_pe at 1e-4, backbone at 1e-5). 328 KB new params — negligible VRAM impact. Builder notes complete and unambiguous.

## design002 — relative_depth_bias
**Date:** 2026-04-03  
**Decision:** APPROVED  
See `runs/idea005/design002/review.md` for full review.  
**Summary:** Tensor shapes verified correct (depth pool→960 patches, Linear(1,70) bias → (B,70,960), expanded to (B*nH,70,960)). Zero-init preserves warm-start identity. attn_mask shape (B*nH,70,960) correct for batch_first=True. 140 new params, ~8.6 MB activation overhead — negligible. Optimizer groups correct. Builder notes complete.

## design003 — depth_conditioned_pe
**Date:** 2026-04-03  
**Decision:** APPROVED  
See `runs/idea005/design003/review.md` for full review.  
**Summary:** Continuous MLP-based PE correction (3→128→256→1024) with near-zero Xavier init preserves warm-start. All tensor shapes verified (depth avg_pool→40×24, coords (B,960,3), pe_correction (B,960,1024)). Optimizer groups correct (depth_cond_pe at 1e-4, backbone at 1e-5). ~296K new params, ~22 MB activations — negligible VRAM. Minor caveat: patch_embed padding=2 causes slight border-patch depth misalignment, not a correctness failure. Builder notes complete.
