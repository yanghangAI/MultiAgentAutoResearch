# Python Orchestrator — Design Plan

Status: design accepted, not yet implemented. Branch: `python-orchestrator`.

## Goal

Replace the LLM-driven Orchestrator (`agents/Orchestrator/prompt.md`) with a Python state machine that reads filesystem state, decides the next action, and shells out to a configurable agent CLI for sub-agent work. Sub-agents (Architect, Designer, Reviewer, Builder, Debugger, Reviser) remain LLM-driven; only the dispatch layer becomes deterministic code.

## Non-goals

- No change to CSV schema or `scripts/cli.py` commands. Sub-agent roles are largely preserved; the one material change is that Builder is now spawned per design and the submit-test/poll/retry loop moves out of Builder into the orchestrator (see "Builder decomposition" below).
- No merging of sub-agents into a shared conversation. File-based handoff stays the source of truth.
- No assumption of any particular agent CLI. Claude Code and Codex are equally first-class backends.

## Architecture

```
scripts/orchestrator.py            ← entry point
scripts/lib/orchestration/
  state.py        ← rich state snapshot: CSV rows + review-file contents
  scheduler.py    ← which eligible idea runs next (FIFO + knobs)
  transitions.py  ← given one idea, what is its next step
  runner.py       ← pluggable agent-CLI adapter (see contract doc)
  judges.py       ← small LLM calls for non-mechanical decisions
```

Filesystem is the only post-invocation truth source. After every CLI script call and every sub-agent invocation, the driver re-snapshots state. No in-memory plan persists across operations.

## State machine

Per iteration:
1. `cli.py sync-status` + `cli.py summarize-results`
2. Re-snapshot.
3. If any idea has zero APPROVED design reviews → spawn **Designer**.
4. If any design has `design.md` but no `design_review.md` → spawn **Reviewer (design)**.
5. If any design has APPROVED design review and no implementation → spawn **Builder**, then enter the driver-owned submit-test loop (see Builder decomposition).
6. If any design is `Implemented` and lacks `code_review.md` → spawn **Reviewer (code)**.
7. If any design has APPROVED code review → `cli.py submit-implemented`.
8. Otherwise → spawn **Architect** (regular or Explorer; see judges).

Transitions are pure functions of the rich-state snapshot. Scheduling across multiple eligible ideas is a separate concern (`scheduler.py`).

## Scheduler

Default policy: FIFO by `idea_id`. Knob in `.automation.json`: `"prefer_in_flight": true|false`. `Expected Designs` in `idea.md` is treated as advisory — it does not gate transitions, but the scheduler may use it to decide whether to keep extending an idea or move on.

## Rich state, not just CSVs

`sync-status` rebuilds tracker CSVs from the filesystem and silently excludes designs without an APPROVED review. The driver therefore reads `design_review.md` and `code_review.md` directly when deciding "retry the same role" vs. "move on." `state.py` joins CSV rows with review-file contents into a single snapshot consumed by `scheduler.py` and `transitions.py`.

## Builder decomposition

Builder no longer owns the submit-test/poll/retry loop. The driver does:

1. Spawn Builder for one design. Builder writes code + `implementation_summary.md` and runs `cli.py review-check-implementation`, then exits.
2. Driver runs `cli.py submit-test`.
3. Driver polls `test_output/` until pass, fail, or timeout.
4. On failure, driver re-spawns Builder with the failure log injected via spawn message. This is a documented exception to the "minimal spawn message" rule (analogous to Debugger receiving a verbatim bug report). Retry budget enforced by the driver, not the Builder agent.

`agents/Builder/prompt.md` must be updated alongside the driver so the agent does not also run its own loop. The driver and prompt edits ship together.

## Pluggable agent backend

The driver makes no assumptions about which agent CLI runs sub-agents. See `docs/agent_runner_contract.md` for the required capability surface. Adapters live in `runner.py`:

- `ClaudeCodeRunner` — wraps `claude -p --append-system-prompt ...`
- `CodexRunner` — wraps `codex exec ...`

Selection per role via `.automation.json`:

```json
{
  "agent_runner": {
    "default": "claude-code",
    "per_role": { "Reviewer": "codex" },
    "claude-code": { "command": "claude", "permission_mode": "bypassPermissions" },
    "codex":       { "command": "codex", "approval_mode": "auto" }
  }
}
```

Both adapters must be working before Phase 3 lands — no "default first, others later." If a configured adapter is missing on the host or fails its capability check, the driver fails loudly at startup.

## Sub-agent invocation contract

- Stdout is used only for exit status and an audit-log tail. No `HANDOFF` schema. Filesystem is re-read for actual state.
- Wall-clock timeout per role.
- Every invocation appends one record to `logs/orchestrator/<timestamp>.jsonl` (cmd, exit code, elapsed, stdout/stderr tail).

## Judgment carve-outs

Three places still need an LLM, each as a short call with deterministic fallback:

| Decision | Default when ambiguous | Rationale |
|---|---|---|
| Explorer vs. regular Architect | regular | safer, less divergence |
| Debugger vs. skip on sub-agent failure | **spawn Debugger** | fail-loud over fail-silent |
| GitHub issue body generation | *not in scope* | dropped until `docs/project_overview.md` provides a verified enablement signal |

Judge calls go through the same `runner.py` abstraction, so per-role backend config applies.

## Concurrency

Serial only. Phase-2 parallel Builders are removed from the migration path — `cli.py submit-implemented` is repo-wide, `setup-design` requires parent `scope_check.pass`, and CSV rewrites are global, so per-idea locks are insufficient. Concurrency is "future work, design TBD."

## Migration plan

1. **Plan + prompt audit.** This document, plus a coordinated prompt-edit pass:
   - `agents/Orchestrator/prompt.md` — reframe or retire (kept as fallback during migration).
   - `agents/Builder/prompt.md` — remove submit-test/poll loop ownership.
   - All sub-agent prompts — replace Claude-Code-specific tool names (`Read`, `Edit`, `Bash`, `WebSearch`, `WebFetch`) with capability descriptions.
   - `setup/Setup_Agent.md`, `README.md` — generalize permission/bypass language.
2. **`--dry-run`.** `state.py` + `scheduler.py` + `transitions.py`. Prints intended action against rich state. No subprocess calls.
3. **`--once`.** Adds `runner.py` with **both** `ClaudeCodeRunner` and `CodexRunner` working. Executes one transition end-to-end including the driver-owned Builder loop. Includes a parity test suite: same spawn message through both adapters against a fixture project, equivalent filesystem outcomes asserted.
4. **`--loop`.** Autonomous mode with timeouts, retries, audit log.
5. **Judges.** Add Explorer/Debugger judges. Remove issue-body judge from scope.
6. **Deprecate LLM Orchestrator.** README points at `scripts/orchestrator.py`. Old prompt kept as fallback.

## Risks

- **Prompt/driver contract mismatch.** An unedited Builder prompt will run its own submit/poll loop while the driver also does, producing duplicate submissions. Mitigation: prompts and driver ship in the same phase.
- **Backend behavior divergence.** `ClaudeCodeRunner` and `CodexRunner` may differ on long stdout, tool errors, interrupted runs. Mitigation: parity test suite in Phase 3.
- **`sync-status` semantic drift.** It rebuilds CSVs from filesystem each run; in-memory state goes stale. Mitigation: re-snapshot after every script and sub-agent call.
- **Headless permission flags.** Each agent CLI needs the right flag to allow file writes and shell execution without interactive prompts. Pinned in the per-runner config; verified at startup.

## Open questions

- Whether judge calls deserve their own short prompt files under `agents/judges/` for review and editing, or live as inline strings in `judges.py`. Leaning toward files for consistency with the rest of the agent prompt system.
- Whether the audit log should be machine-queryable (JSONL with a stable schema) from day one or evolve into one. Leaning toward stable schema from day one — it is cheap upfront and the Reviewer/Architect could read it later.
