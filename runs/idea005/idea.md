# Depth-Aware Positional Embeddings

**Expected Designs:** 3

**Concept:** 
Provide explicit geometric awareness to the Transformer, which currently only uses standard 2D positional encodings. Inject depth values or structure into the positional embeddings.

**Search Options:** 
- `standard_2d_pe`: (Current Baseline) 2D positional embedding.
- `discretized_depth_pe`: Provide discretized bucketed depth positional embeddings.
- `relative_depth_bias`: Introduce relative depth biases to the queries.