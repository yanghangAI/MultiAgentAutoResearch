# Agent Runner Contract

Status: design. Used by the Python orchestrator (`docs/python_orchestrator.md`) to invoke LLM sub-agents through any compatible CLI.

## Why

This project does not commit to a single agent CLI. Users may run sub-agents through Claude Code, Codex, or any other CLI/SDK whose tool surface satisfies this contract. Adding a new backend means writing one adapter against this contract; nothing else in the orchestrator changes.

## Interface

```python
class AgentRunner(Protocol):
    name: str

    def is_available(self) -> bool:
        """Return True if the underlying CLI is installed and authenticated.
        Called at orchestrator startup. False here is a hard error."""

    def capabilities(self) -> set[Capability]:
        """Return the capability set this runner provides. Must be a superset
        of Capability.REQUIRED for sub-agent use."""

    def run(self, *,
            prompt_file: Path,        # absolute path to agents/<role>/prompt.md
            spawn_message: str,       # the minimal spawn message
            cwd: Path,                # the project root
            timeout_s: int) -> RunResult: ...
```

`RunResult` carries `exit_code: int`, `stdout_tail: str`, `stderr_tail: str`, `elapsed_s: float`. No structured handoff data — the orchestrator re-reads the filesystem for actual state.

## Required capabilities

The agent CLI must be able to, within the project working directory and without further user interaction:

| Capability | Why it is needed |
|---|---|
| `FILE_READ` | Sub-agents read prompts, CSVs, design files, code. |
| `FILE_WRITE` | Builder writes code, Designer writes `design.md`, Reviewer writes review files. |
| `SHELL_EXEC` | Sub-agents run `python scripts/cli.py …` (e.g. `setup-design`, `review-check-implementation`, `sync-status`). Note: `submit-test` and the test-completion poll are run by the orchestrator, not by Builder. |
| `WEB_SEARCH` | Architect uses bounded literature searches. |
| `WEB_FETCH` | Architect reads abstracts. |

A runner whose CLI cannot deliver all of `FILE_READ`, `FILE_WRITE`, `SHELL_EXEC` is unusable. `WEB_SEARCH` / `WEB_FETCH` are required only when the runner is configured for the Architect role.

## Operational requirements

- **Non-interactive.** The CLI must not prompt the user for permission during a run. Headless / bypass / auto-approve mode is configured once in `.automation.json` and validated by `is_available()`.
- **Fresh context per call.** Each invocation is independent. The orchestrator does not rely on session resume across calls.
- **Exit code discipline.** Zero on success, non-zero on failure (timeout, tool error, internal crash). The orchestrator treats non-zero as "this invocation did not complete its task" and either retries, classifies as infra bug, or skips, per the run loop.
- **Bounded stdout.** The runner caps captured stdout/stderr to a configurable tail (default 8 KB each) for the audit log. Full output goes to a per-invocation log file under `logs/orchestrator/`.

## Configuration

Each runner reads its own config block from `.automation.json` under `agent_runner.<name>`. Required keys are runner-defined (e.g. `command`, `permission_mode` for Claude Code; `command`, `approval_mode` for Codex). The orchestrator passes the block to the adapter at construction time.

## Adapters provided

| Name | Backing CLI | Status |
|---|---|---|
| `claude-code` | `claude -p` | planned, Phase 3 |
| `codex` | `codex exec` | planned, Phase 3 |

Both adapters must be working before any single-runner code lands — see Phase 3 in `docs/python_orchestrator.md`. A parity test suite asserts equivalent filesystem outcomes from the same spawn message run through each adapter against a fixture project.

## Adding a new adapter

1. Implement the `AgentRunner` protocol.
2. Verify `is_available()` checks installation and authentication, not just `which <cmd>`.
3. Verify `capabilities()` is honest — declared capabilities must actually work end-to-end on a fixture project.
4. Add the new adapter to the registry in `scripts/lib/orchestration/runner.py`.
5. Document the config block keys.
6. Add the adapter to the parity test suite.

No other orchestrator code should need to change.
