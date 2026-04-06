import sys
import re

with open("baseline.py", "r") as f:
    text = f.read()

# Extract from METRICS & LOSS to end of file or to TRAIN / VAL LOOPS
metrics_start = text.find("# ── METRICS & LOSS")
val_start = text.find("@torch.no_grad()\ndef validate")
val_end = text.find("def main():")

# We want to extract METRICS & LOSS block, EXCLUDING LR SCHEDULE
# And the validate function.
metrics_code = text[metrics_start:text.find("# ── LR SCHEDULE")]
val_code = text[val_start:val_end]

# Remove them from baseline.py
new_text = text.replace(metrics_code, "")
new_text = new_text.replace(val_code, "")

# We need to add the imports for them
import_str = "    save_checkpoint, load_checkpoint,\n)"
new_import_str = "    save_checkpoint, load_checkpoint,\n    validate, pose_loss, mpjpe, recover_pelvis_3d, pelvis_abs_error, BODY_IDX, HAND_IDX\n)"
new_text = new_text.replace(import_str, new_import_str)

with open("baseline.py", "w") as f:
    f.write(new_text)

with open("infra.py", "a") as f:
    f.write("\n\n" + metrics_code.strip() + "\n\n" + val_code.strip() + "\n")

print("Done")
