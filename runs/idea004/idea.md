# Layer-Wise Learning Rate Decay & Progressive Unfreezing

**Expected Designs:** 6

**Concept:** 
Use structure in how the backbone learns to prevent catastrophic forgetting of the ViT's rich pre-trained RGB features while adapting it to depth. Give different learning rates to different depths.

**Search Options:** 
- Vary LLRD decay factor gamma.
- Vary ViT unfreeze epoch.