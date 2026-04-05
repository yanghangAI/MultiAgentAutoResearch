# Kinematic Attention Masking

**Expected Designs:** 3

**Concept:** 
Human pose estimation models often predict physically impossible poses because the attention mechanism lacks explicit structural constraints. Kinematic Attention Masking restricts self-attention weights between structurally distant joints in the final decoding layers, enforcing anatomical plausibility.

**Search Options:** 
- `dense`: (Current baseline) Unconstrained full self-attention across all patch tokens.
- `soft_kinematic_mask`: Apply a soft penalty map prioritizing attention between connected limbs and joints according to the human kinematic tree.
- `hard_kinematic_mask`: Hard mask restricting attention solely to a localized neighborhood in the kinematic graph (e.g., radius of 2 hops).

**Architect's Instruction for Designer:**
I require exactly **3** detailed designs for this idea. Please proceed to generate these 3 variations and query me with your designs.
