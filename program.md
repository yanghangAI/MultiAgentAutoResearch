# autosapiens — BEDLAM2 3D Pose

Autonomous research loop for the BEDLAM2 RGBD 3D pose project.
Adapted from [karpathy/autoresearch](https://github.com/karpathy/autoresearch).


---

## Setup

To set up a new research session, work with the user to:
1. **Understand sapiens3d** Read the code and docs in `sapiens`, or ask questions to user until you understand sapiens3d. 
2. **Read the in-scope files** for full context (the repo uses mmengine):
   - `program.md` — you are reading it now.
   - `train.py` — **the file you edit**. Full standalone MMEngine config.
   - `sapiens/pose/mmpose/models/heads/regression_heads/pose3d_transformer_head.py` — default head.
   - `sapiens/pose/mmpose/models/heads/regression_heads/pose3d_regression_head.py` — baseline head.
   - `sapiens/pose/mmpose/models/backbones/sapiens_rgbd.py` — 4-channel ViT backbone.
   - `sapienspose/CLAUDE.md` — project conventions and gotchas (read before touching any code).
3. **Check data exists**: `ls /app/data/` — should show sequence directories. If missing, tell the human.
4. **Create the runs root**: `mkdir -p /app/autosapiens/runs`
5. **Initialize results.md**: Create `autosapiens/results.md` with just the header row.
6. **Confirm and go**: confirm setup looks good, then start the loop.

---

## What the experiment does

Each experiment runs `train.py` with a **fixed 1-epoch budget** on 300 training sequences / 100 val sequences. This makes every experiment directly comparable regardless of architecture or hyperparameter changes.

**The metric is `val_mpjpe_body` (mm) — lower is better.**
This is mean per-joint position error on 22 body joints in camera space (root-relative).

Typical baseline values at 1 epochs with 300 training sequences ≈ 280 mm (transformer head).

---

## What you CAN do

This is a docker image, so don't worry about destroying anything, feel free to make any change without asking for permission.

You can do anything you can to improve the `val_mpjpe_body` as long as it is not list in 'What you CANNOT do'


## What you CANNOT do

- Change `num_epochs`, `train_max_seqs`, `val_max_seqs` — these are the fixed budget.
- Modify the evaluation metric (`mmpose/evaluation/metrics/bedlam_metric.py`).
- Modify the dataset or data loading infrastructure.
- Install new packages.


---

## Logging results

When an experiment is done, log it to `autosapiens/results.md`

---

## The experiment loop

LOOP FOREVER:

1. Pick an experimental idea.
2. Write your idea into idea.md, put it into `runs/$run_id$/idea.md`.
3. Implement your idea in `train.py` (or any other code you need.)
4. Run `train.py`.
5. Save the results into results.md.
6. If crash: inspect log, attempt quick fix and re-run. After 2 failed attempts, log as crash and revert.


**Simplicity criterion**: all else equal, simpler is better. A 1 mm gain from 20 lines of
hacky code or 20% more training time is not worth it. Removing code and matching or beating the baseline? Always keep.

**Crashes**: if the idea is fundamentally broken (OOM from a huge model, wrong tensor shape),
log as crash, revert, move on. If it's a trivial fix (typo, import), fix and re-run.

**What you need to save in runs**: During each run, save config and an expl



**NEVER STOP**: once the loop begins, do NOT pause to ask the human whether to continue.
The human expects you to run indefinitely until manually stopped. If you run out of obvious
ideas, try combining near-misses, try more radical architectural changes, re-read the head
and backbone code for inspiration. The loop runs until you are interrupted.

---

**girll me**: Before you start, interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

If a question can be answered by exploring the codebase, explore the codebase instead.


## Key background (read before starting)

- Coordinate system: BEDLAM2 camera space is **X=forward (depth), Y=left, Z=up** —
  differs from OpenCV. Projection: `u = fx·(-Y/X) + cx`, `v = fy·(-Z/X) + cy`.
- 70 active joints: 22 body + 2 eyes + 30 hands + 16 surface. Defined in
  `mmpose/datasets/datasets/body3d/constants.py`.
- `mpjpe/body/val` = MPJPE on the 22 body joints only (most important metric).
- The transformer head (`Pose3dTransformerHead`) uses per-joint query tokens + cross-attention
  over the backbone feature map. It currently outperforms the regression head.
- `persistent_workers=False` is required — NPZ/mmap file descriptor issue; do NOT change.
- MMEngine gotcha: val metainfo fields are flattened to the top level dict in `metric.process()`.
  Read as `data_sample['K']`, not `data_sample['metainfo']['K']`.
