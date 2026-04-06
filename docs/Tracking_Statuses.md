# Tracking Status Explanations

The automated research pipeline uses several explicit states to track the progression of both broad **Ideas** and individual **Designs** (variations). These statuses dictate which agent is responsible for the next step of the pipeline. They are recorded in `runs/idea_overview.csv` and each idea's `design_overview.csv`.

The script status logic now lives in `scripts/lib/status.py`, and `python scripts/cli.py sync-status` uses these exact string matches to manage state automatically.

---

## Design Statuses

These represent the lifecycle of a specific mathematical or architectural variation (`design.md`) drafted by the **Designer**.

| Status | Description | Next Steps |
| :--- | :--- | :--- |
| **Not Implemented** | The Designer has drafted `design.md` and the Architect has reviewed and `APPROVED` it. The Builder has either not started writing the code yet, or the code currently fails tests/reviews. | The **Builder** needs to write `train.py`, run a local 2-epoch sanity test (`python scripts/cli.py submit-test <design_dir>`), and get code approval from the Designer. |
| **Implemented** | The Builder's `train.py` successfully passed the sanity test and the **Designer explicitly `APPROVED` the code** in `code_review.md`. | The **Runner** needs to submit this design to the SLURM cluster for full 20-epoch training (`python scripts/cli.py submit-train <train.py> <job_name>`). |
| **Training** | The SLURM job is actively running. Evaluated automatically by `python scripts/cli.py sync-status` when it finds entries for this design in the global `results.csv`, but the highest recorded epoch is `< 20`. | Wait for the cluster to finish the run. The **Runner** monitors node usage and logs. |
| **Done** | The design has successfully finished its full training budget. Evaluated automatically when the design's highest epoch reaches `20` in `results.csv`. | No further action required for this specific design. |

---

## Idea Statuses

These represent the overarching progress of a broad concept proposed by the **Architect**. An Idea's status cascades upwards based mathematically on the lowest common denominator of its constituent Designs.

| Status | Description | Next Steps |
| :--- | :--- | :--- |
| **Not Designed** | The Architect has proposed the idea (saved in `idea.md`), but the exact technical variations have not yet been drafted or approved. | The **Designer** must draft `design.md` variations, and the **Architect** must review them. |
| **Designed** | All requested design variations have been drafted and approved. However, some or all of the designs are still legally marked as `Not Implemented`. | The **Builder** must implement the code for the remaining `Not Implemented` designs. |
| **Implemented** | **All** designs under this idea have achieved at least `Implemented` status (meaning the code is written, tested, and reviewed by the Designer). | The **Runner** must submit the remaining implemented jobs to the main SLURM queue. |
| **Training** | **All** active designs under this idea have explicitly started training (all designs are individually marked as either `Training` or `Done`, but not all are `Done`). | Wait for the remaining SLURM jobs to conclude and generate their 20th epoch results. |
| **Done** | **All** design variations under this idea have reached 20 epochs in `results.csv`. | The **Architect** can use the finalized metrics from this Idea to inspire their next novel `Not Designed` proposal. |
