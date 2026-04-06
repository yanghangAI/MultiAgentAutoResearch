# Tracking Statuses

Statuses are stored in `runs/idea_overview.csv` and `runs/<idea_id>/design_overview.csv`.

## Design Statuses

- `Not Implemented`: design approved, implementation not ready.
- `Implemented`: code approved and ready for full submission.
- `Submitted`: job submitted, not yet reflected in final metrics.
- `Training`: metrics present but completion criterion not reached.
- `Done`: completion criterion reached.

Completion behavior is configurable in `.automation.yaml` (`status.done_epoch`).

## Idea Statuses

- `Not Designed`: expected designs not fully drafted/approved.
- `Designed`: all designs exist but implementation not complete.
- `Implemented`: all designs at least implemented/submitted/training/done.
- `Training`: all designs in training/done, but not all done.
- `Done`: all designs done.
