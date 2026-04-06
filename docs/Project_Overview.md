# Project Overview: 3D Human Pose Estimation from RGB-D images

This project is focused on fine-tuning **Sapiens** (a Foundation Vision Transformer model from Meta) to predict 3D joint positions using the **BEDLAM2** dataset from RGB-D images.

Here is a breakdown of what the project is doing based on its structure:

1. **Model Adaptation**: It modifies the Sapiens 0.3B Vision Transformer (which natively takes RGB) to accept a 4-channel input (`RGB + Depth`). It then adds a custom Transformer Decoder head (`Pose3DHead`) that maps these features into 70 root-relative 3D joint positions in space.

2. **Training & Orchestration**: 
   - `baseline.py` is the main deep learning training flow.
   - It runs on an HPC system using the SLURM workload manager, with CLI-driven submission layered over `scripts/slurm/slurm_test.sh` and `scripts/slurm/slurm_train.sh`.
   - The `runs/` directory stores training outputs like metrics, TensorBoard logs, and saved checkpoints.

3. **Automated Search Space/MLOps (AutoML)**: The `docs/` folder contains documents like `Orchestrator.md`, `Architect.md`, and `Designer.md`, which indicates there is a surrounding autonomous pipeline designed to search for optimal model architectures, data features, and hyperparameters across different runs.

4. **Sapiens Framework**: The `sapiens/` directory contains a fork of the foundation model setup itself, including OpenMMLab libraries (MMEngine, MMCV, MMDetection, MMPose, MMSegmentation) tailored for human-centric vision tasks.
