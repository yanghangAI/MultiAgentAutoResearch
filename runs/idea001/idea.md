# RGB-D Modality Fusion Strategy

**Expected Designs:** 3

**Concept:** 
The Sapiens baseline uses 'early fusion' by modifying the first patch embedding layer for 4-channel input. This potentially disrupts learned RGB representations. We want to test different fusion points.

**Search Options:** 
- `early_4ch`: (Current baseline) Early fusion in the patch embedding.
- `mid_fusion`: Fuse depth embeddings halfway through the ViT layers.
- `late_cross_attention`: Process RGB only in the ViT, then use depth as queries in a cross-attention transformer layer before the pose head.

**Architect's Instruction for Designer:**
I require exactly **3** detailed designs (one for each fusion strategy) for this idea. Please proceed to generate these 3 variations and query me with your designs.