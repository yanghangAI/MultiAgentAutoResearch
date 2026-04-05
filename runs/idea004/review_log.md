Design_ID: design001
Status: APPROVED
Feedback: The design addresses catastrophic forgetting through constant decay LLRD with progressive unfreezing. Mathematical specification is clear, implementable within budget. Monitor vanishing learning rates in deep layers; ensure layer definitions are explicit in code. Only 15 active training epochs; watch for adaptation adequacy.
---
Design_ID: design001
Status: APPROVED
Feedback: LLRD formula and optimizer rebuild are mathematically correct. `model.backbone.vit.layers` confirmed valid. No new parameters; fits 11GB budget easily. base_lr_backbone=1e-4 is 10x above baseline — monitor for instability epochs 3–4. Shallow blocks lack warmup at unfreeze but mitigated by low LRs (~3e-5). Only 15 epochs for shallow blocks is an accepted tradeoff. APPROVED.
Design_ID: design002
Status: APPROVED
Feedback: LLRD formula is mathematically correct and consistent with design001 convention. Verified: block 23 lr=1e-4, block 0 lr≈8.9e-6, embed lr≈8.0e-6, yielding ~11x deep-to-shallow ratio (vs ~3x in design001). No new parameters introduced; memory budget well within 11GB. Optimizer rebuild at epoch 5 is clearly specified with scaler state restoration and per-group `initial_lr` assignment before LR scale application — implementation is sound. base_lr_backbone=1e-4 (10x baseline) carries mild instability risk during epochs 3–4 (post-warmup, pre-unfreeze), but same risk exists in design001 with no evidence of failure. Shallow blocks have no dedicated warmup at unfreeze epoch 5, but their LRs (~8–9e-6) are low enough to mitigate instability. The gamma=0.90 choice is a distinct and valid variation from design001 (gamma=0.95), isolating the decay factor effect while holding unfreeze_epoch=5 constant. Only 15 effective training epochs for shallow blocks is an accepted tradeoff consistent with the idea's progressive unfreezing strategy. APPROVED.
---

Design_ID: design003
Status: APPROVED
Feedback: LLRD formula is mathematically correct. Minor prose inconsistency: overview states "~21x ratio" but the actual block23/block0 ratio is ~48x (1e-4 / 2.096e-6); the rationale and computed values are correct. No new parameters; fits 11GB budget. Progressive unfreezing and optimizer rebuild at epoch 5 are well-specified, consistent with designs 001/002. Shallow block LRs (~2e-6) leave blocks 0–5 nearly frozen post-unfreeze — acceptable given design's intent to probe the decay extreme. base_lr_backbone=1e-4 carries mild instability risk epochs 3–4, same as prior designs. Constants unchanged. APPROVED.
---

Design_ID: design004
Status: APPROVED
Feedback: LLRD formula correct (block 23: 1e-4, block 0: ~3.073e-5, embed: ~2.919e-5). Cosine scale at epoch 10 ≈ 0.634 verified. Optimizer rebuild procedure (13 → 26 groups) is clearly specified with scaler state restoration. No new parameters; fits 11GB budget. Shallow blocks have only 10 post-unfreeze epochs with decaying LR — intentional tradeoff, isolates timing effect vs design001. base_lr_backbone=1e-4 carries same mild instability risk as prior designs. APPROVED.
---

Design_ID: design005
Status: APPROVED

Design_ID: design006
Status: APPROVED
