# Python Orchestrator Migration — Handoff

Branch: `python-orchestrator` (ahead of `main` by 12 commits as of `7e6bdf2`).
Status: Phases 1–3 complete. Phase 4 (`--loop`) and Phase 5 (judges + LLM-Orchestrator deprecation) are unstarted.

Design docs (read first):
- `docs/python_orchestrator.md` — full plan, state machine, migration phases.
- `docs/agent_runner_contract.md` — pluggable-CLI capability surface.

Tests: `131 passed` on the branch (`python -m pytest tests/scripts/`).

---

## What landed (per phase)

### Phase 1 — Plan + prompt audit
- `docs/python_orchestrator.md`, `docs/agent_runner_contract.md` written and converged with Codex.
- `agents/Builder/prompt.md` rewritten to a per-design contract: Builder implements one design, runs `review-check-implementation`, and exits. The submit-test/poll/retry loop is the orchestrator's job.
- `agents/Orchestrator/prompt.md` reframed as the LLM fallback (preferred runtime is now the Python driver). Identifier-passing rules and Builder section updated to match the per-design contract.
- Claude-Code-specific tool names (`WebSearch`, `WebFetch`) replaced with capability descriptions in Architect prompts. `README.md` and `setup/Setup_Agent.md` generalized to "any agent CLI."
- Setup_Agent test-completion procedure moved from the Builder prompt to `.automation.json`/orchestrator config.

### Phase 2 — `--dry-run`
- `scripts/orchestrator.py` entry point with `--dry-run` and `--prefer-in-flight`.
- `scripts/lib/orchestration/state.py` — rich filesystem snapshot (CSV rows joined with raw review-file contents, ancestor-taint propagation via `scope.is_tainted`).
- `scripts/lib/orchestration/transitions.py` — per-idea action selection. Five priority-ordered rules: design review → Designer → Builder → code review → Submit. Tainted designs are skipped by Builder/Submit.
- `scripts/lib/orchestration/scheduler.py` — FIFO ordering by `idea_id` with a `prefer_in_flight` knob (in-flight = at least one approved design review).
- 16 tests covering every transition rule plus scheduler behavior.

### Phase 3a — Runner abstraction + one-shot dispatch
- `scripts/lib/orchestration/runner.py` — `AgentRunner` protocol, `Capability` enum, `ClaudeCodeRunner`, `CodexRunner`, registry, config loader.
- Both adapters use a `command_template` argv list with a `{spawn_message}` sentinel; users override via `.automation.json` `agent_runner.<name>.command_template`.
- `validate_all_runners()` runs at startup in `--once` mode and fails loudly on any unknown name or missing CLI (including `per_role` entries the current invocation will not actually use).
- `--once` mode dispatches the chosen action through the configured runner, or runs `cli.py submit-implemented` for Submit actions. Audit log at `logs/orchestrator/<YYYYMMDD>.jsonl` carries a per-invocation `session_id`.
- Subprocess output streams to disk (tempfile by default; persistent path when caller supplies one) so long Builder runs do not balloon memory; 8 KB tails captured into `RunResult` for the audit log.
- 20 runner tests covering parity, config loading, registry, startup validation, capability declarations.

### Phase 3b — Driver-owned Builder retry loop
- `scripts/lib/orchestration/builder_loop.py` — the loop the Builder prompt now defers to.
  - Spawn → check for `implement_failed.md` → `cli.py submit-test` → poll for outcome → classify pass/fail → respawn with failure log, up to `max_test_attempts`.
  - On budget exhaustion the driver writes `implement_failed.md` itself (refuses to clobber a Builder-written one).
  - Outcome detection: configured shell command (exit codes `0`/`1`/`2`/other = `PASS`/`FAIL`/`STILL_RUNNING`/`ERROR`) **or** the built-in default (`training_failed.txt` → FAIL; `test_output/metrics.csv` with ≥2 lines → PASS; else still running).
  - Failure log injected inline into the next spawn message if it fits under `failure_log_max_inline_bytes` (default 4 KB); else spilled to `<design_dir>/last_failure.log` and referenced by path.
- `--once` routes `Builder` actions through `run_builder_loop`; per-attempt audit records carry an `attempt_session_id` derived from the parent invocation's `session_id`.
- 13 loop tests covering: default outcome modes, shell-command mode, poll timeout, config overrides, pass-on-first/second attempt, budget exhaustion, Builder giving up cleanly, large failure log spilled to file, audit-log session correlation.

Each phase passed a Codex review pass; review findings were folded back in before the next phase started.

---

## What's still pending

### Phase 4 — `--loop` (autonomous mode)
The plan in `docs/python_orchestrator.md` calls for:
- Continuous loop: snapshot → pick → execute → re-snapshot → repeat.
- Per-role timeouts (already configurable, but not yet enforced loop-wide).
- Audit log already in place; loop mode reuses it.
- Sleep/backoff between iterations when no actionable work exists.
- Graceful stop on SIGINT.

Open question: should `--loop` run a configurable number of iterations or until SIGINT? Plan is silent; pick a default and document.

### Phase 5 — Judges + LLM-Orchestrator deprecation
Three judge calls in the plan, each with a deterministic fallback already chosen:
- Explorer-vs-regular Architect (default: regular).
- Debugger-vs-skip on sub-agent failure (default: spawn Debugger — fail-loud).
- ~~GitHub issue body generation~~ (dropped; revisit only if `docs/project_overview.md` lands).

Judges should reuse `runner.py` so per-role backend config (e.g. cheaper Codex for judges) just works.

After judges are in, the README should point at `scripts/orchestrator.py` as the primary runtime; `agents/Orchestrator/prompt.md` stays as a fallback.

### Known gaps Codex flagged but did not block on
- ARG_MAX guard for *very* long failure logs is implemented (spill-to-file). The remaining edge case is a spawn message that is itself extreme (unlikely in practice). No action needed unless it shows up.
- Streaming subprocess output is in place; no real-time monitoring of in-flight runs (e.g. for a Phase-4 dashboard). Out of scope until needed.
- `_AuditLogger` is currently in `builder_loop.py` and imported as a private name from `scripts/orchestrator.py`. If Phase 4 introduces other multi-step roles, lift it into its own module.
- Reviewer is single-shot today. If code-review rejection should respawn Builder (the 3-rejection budget mentioned in the plan), that loop is **not yet wired** — plumbing exists in `BuilderLoopConfig.max_code_review_rejections` but no consumer reads it. Likely Phase 4 work.

---

## How to verify the branch on a fresh checkout

```bash
git checkout python-orchestrator
python -m pytest tests/scripts/                    # expect 131 passed
python scripts/orchestrator.py --dry-run           # prints next intended action

# If a configured agent CLI is on PATH:
python scripts/orchestrator.py --once              # executes one transition
```

`.automation.json` keys this branch consumes (all optional with sensible defaults):

```json
{
  "agent_runner": {
    "default": "claude-code",
    "per_role": { "Reviewer": "codex" },
    "claude-code": { "command_template": ["claude", "-p", "{spawn_message}", "--permission-mode", "bypassPermissions"] },
    "codex":       { "command_template": ["codex", "exec", "{spawn_message}"] }
  },
  "builder_loop": {
    "max_test_attempts": 10,
    "max_code_review_rejections": 3,
    "poll_interval_s": 30,
    "test_timeout_s": 1800,
    "outcome_check_command": null,
    "failure_log_max_inline_bytes": 4096
  }
}
```

---

## Key files (quick map)

| File | Role |
|---|---|
| `scripts/orchestrator.py` | Entry point. `--dry-run` and `--once`. |
| `scripts/lib/orchestration/state.py` | Rich filesystem snapshot. |
| `scripts/lib/orchestration/transitions.py` | Per-idea action selection. |
| `scripts/lib/orchestration/scheduler.py` | Cross-idea ordering. |
| `scripts/lib/orchestration/runner.py` | Pluggable agent-CLI adapters. |
| `scripts/lib/orchestration/builder_loop.py` | Driver-owned Builder retry loop. |
| `agents/Builder/prompt.md` | Per-design contract; no submit-test ownership. |
| `agents/Orchestrator/prompt.md` | LLM fallback; matches the per-design contract. |
| `docs/python_orchestrator.md` | Full plan. |
| `docs/agent_runner_contract.md` | Capability surface for new adapters. |
| `tests/scripts/test_orchestration.py` | 16 transition/scheduler tests. |
| `tests/scripts/test_runner.py` | 20 runner tests. |
| `tests/scripts/test_builder_loop.py` | 13 Builder-loop tests. |

---

## Recommended next session

1. Re-read `docs/python_orchestrator.md` (the migration plan now reflects 3a/3b split).
2. Decide Phase 4 stop condition (iterations vs. SIGINT-only) and add it to the plan.
3. Implement `--loop` reusing existing components — most of the work is signal handling, sleep policy, and a top-level loop calling the existing `pick_next` + dispatch.
4. Run a Codex review pass before merging (the pattern this branch followed: ship a phase, ask Codex to push back, fold in findings, then move on).

The branch is publishable as a draft PR against `main` whenever you want external review; nothing on it depends on un-pushed work.
