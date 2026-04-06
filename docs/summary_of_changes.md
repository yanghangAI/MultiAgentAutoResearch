# Migration Summary

This repository was refactored from a model-specific project into a reusable experiment automation template.

Key migration outcomes:

1. Removed model/dataset-specific training code and assets.
2. Added `.automation.yaml` for project-level behavior.
3. Refactored scripts to be config-driven for metrics, status completion, setup-design, submission, and dashboard.
4. Kept the agent pipeline scaffold and tracking architecture.
