# Summary of Changes made to `docs/`

1. **Created Prompts Directory**: Created a new `docs/prompts/` subfolder to keep the workspace strictly organized.
2. **Relocated Agent Instructions**: Moved all agent prompt markdown files (such as `Orchestrator.md`, `SearchSpaceArchitect.md`, `ExperimentDesigner.md`, `ProxyEnvironmentBuilder.md`, `ExecutionOrchestrator.md`, and `CrossSceneValidator.md`) from the root `docs/` folder into `docs/prompts/`.
3. **Updated Internal Pathing**: Ran batch `sed` commands to update all internal file references inside the markdown files, ensuring they point accurately to the new `docs/prompts/*.md` locations.
4. **Updated Terminology**: Modified the documentation to reflect the new naming conventions for runs, updating references from `exp` to `idea` (e.g., updating paths to `runs/idea_overview.csv` and `runs/idea*/design_overview.csv`).
