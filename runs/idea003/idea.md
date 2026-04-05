# Curriculum-Based Loss Weighting

**Expected Designs:** 2

**Concept:** 
Absolute depth is hard and creates noisy gradients early on. It needs a learned or structured loss weighting over epochs to stabilize relative pose training.

**Search Options:** 
- `constant`: (Current Baseline) Fixed weights for depth, pose, UV losses.
- `linear_warmup`: Progressively increase depth loss weight.
- `homoscedastic_uncertainty`: Learnable loss weighting based on uncertainty.