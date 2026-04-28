"""Pluggable agent-CLI runners.

The orchestrator does not commit to a single agent CLI. Each adapter wraps
a different command-line agent (Claude Code, Codex, or any other CLI that
satisfies docs/agent_runner_contract.md) so the same spawn message can be
dispatched through whichever backend is configured.

Configuration lives in `.automation.json` under the `agent_runner` block.
Default config (used when the block is absent) routes everything to
`claude-code`. Per-role overrides allow e.g. running Reviewer through Codex
for a second-opinion read.

Adapters expose:
  - `name`             — the registry key.
  - `is_available()`   — does the underlying CLI exist on PATH?
  - `build_command(message)` — argv list (testable in isolation).
  - `run(...)`         — execute the command, return RunResult.

The runner never inspects sub-agent stdout for handoff data; the driver
re-snapshots the filesystem after every call. Stdout/stderr tails are
captured into RunResult for the audit log only.
"""

from __future__ import annotations

import enum
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


SPAWN_PLACEHOLDER = "{spawn_message}"
DEFAULT_OUTPUT_TAIL_BYTES = 8 * 1024


class Capability(enum.Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    SHELL_EXEC = "shell_exec"
    WEB_SEARCH = "web_search"
    WEB_FETCH = "web_fetch"


# Sub-agents need at minimum these three. Web access is required only for
# Architect; runners that lack it can still serve Designer/Reviewer/Builder.
REQUIRED_CAPABILITIES: frozenset[Capability] = frozenset(
    {Capability.FILE_READ, Capability.FILE_WRITE, Capability.SHELL_EXEC}
)


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    stdout_tail: str
    stderr_tail: str
    elapsed_s: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class AgentRunner(Protocol):
    name: str

    def is_available(self) -> bool: ...
    def capabilities(self) -> frozenset[Capability]: ...
    def build_command(self, spawn_message: str) -> list[str]: ...
    def run(
        self,
        *,
        prompt_file: Path,
        spawn_message: str,
        cwd: Path,
        timeout_s: int,
    ) -> RunResult: ...


class _TemplateRunner:
    """Shared implementation for adapters that drive a CLI via argv template.

    The template is a list of strings; one element is the sentinel
    `{spawn_message}` and is replaced at call time with the actual spawn
    message. This keeps adapters declarative and easy to override via
    `.automation.json`.
    """

    name: str
    default_template: tuple[str, ...] = ()
    declared_capabilities: frozenset[Capability] = frozenset(
        {
            Capability.FILE_READ,
            Capability.FILE_WRITE,
            Capability.SHELL_EXEC,
            Capability.WEB_SEARCH,
            Capability.WEB_FETCH,
        }
    )

    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        template = cfg.get("command_template")
        if template:
            self._template = tuple(template)
        else:
            self._template = self.default_template
        if SPAWN_PLACEHOLDER not in self._template:
            raise ValueError(
                f"runner {self.name!r} command_template must contain "
                f"the {SPAWN_PLACEHOLDER!r} sentinel; got {list(self._template)}"
            )

    @property
    def command(self) -> str:
        return self._template[0]

    def is_available(self) -> bool:
        return shutil.which(self.command) is not None

    def capabilities(self) -> frozenset[Capability]:
        return self.declared_capabilities

    def build_command(self, spawn_message: str) -> list[str]:
        return [
            spawn_message if part == SPAWN_PLACEHOLDER else part
            for part in self._template
        ]

    def run(
        self,
        *,
        prompt_file: Path,
        spawn_message: str,
        cwd: Path,
        timeout_s: int,
    ) -> RunResult:
        # `prompt_file` is an existence guard, not piped to the child.
        # Sub-agents load their own prompt via the spawn message ("Read ...").
        # Passing the file here lets the runner fail fast if the prompt is
        # missing, without coupling adapters to specific CLI flags for
        # system-prompt injection.
        if not prompt_file.is_file():
            raise FileNotFoundError(f"prompt file not found: {prompt_file}")
        argv = self.build_command(spawn_message)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            elapsed = time.monotonic() - start
            return RunResult(
                exit_code=proc.returncode,
                stdout_tail=_tail(proc.stdout),
                stderr_tail=_tail(proc.stderr),
                elapsed_s=elapsed,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - start
            return RunResult(
                exit_code=-1,
                stdout_tail=_tail(exc.stdout or ""),
                stderr_tail=_tail(exc.stderr or ""),
                elapsed_s=elapsed,
                timed_out=True,
            )


class ClaudeCodeRunner(_TemplateRunner):
    name = "claude-code"
    default_template = (
        "claude",
        "-p",
        SPAWN_PLACEHOLDER,
        "--permission-mode",
        "bypassPermissions",
    )


class CodexRunner(_TemplateRunner):
    name = "codex"
    default_template = (
        "codex",
        "exec",
        SPAWN_PLACEHOLDER,
    )


_REGISTRY: dict[str, type[_TemplateRunner]] = {
    ClaudeCodeRunner.name: ClaudeCodeRunner,
    CodexRunner.name: CodexRunner,
}


def register_runner(cls: type[_TemplateRunner]) -> None:
    """Register an additional runner type. Used for tests and out-of-tree adapters."""
    _REGISTRY[cls.name] = cls


def load_runner_config(root: Path) -> dict:
    """Read the agent_runner block from .automation.json. Empty dict if absent."""
    cfg_path = root / ".automation.json"
    if not cfg_path.is_file():
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    block = data.get("agent_runner")
    return block if isinstance(block, dict) else {}


def configured_runner_names(root: Path) -> set[str]:
    """Every runner name referenced by .automation.json (default + per_role)."""
    cfg = load_runner_config(root)
    names: set[str] = set()
    default = cfg.get("default") or "claude-code"
    names.add(default)
    per_role = cfg.get("per_role") or {}
    if isinstance(per_role, dict):
        for value in per_role.values():
            if isinstance(value, str):
                names.add(value)
    return names


def validate_all_runners(root: Path) -> None:
    """Construct every configured runner and verify it is on PATH.

    Called at orchestrator startup so a typo or a missing CLI is surfaced
    immediately, even if the chosen role for this invocation does not need
    that runner. Raises ValueError or RuntimeError on the first failure.
    """
    cfg = load_runner_config(root)
    for name in sorted(configured_runner_names(root)):
        if name not in _REGISTRY:
            raise ValueError(
                f"unknown runner {name!r} in .automation.json agent_runner; "
                f"registered: {sorted(_REGISTRY)}"
            )
        runner_cls = _REGISTRY[name]
        runner_cfg = cfg.get(name, {}) if isinstance(cfg.get(name), dict) else {}
        runner = runner_cls(runner_cfg)
        if not runner.is_available():
            raise RuntimeError(
                f"runner {name!r} is configured in .automation.json but its "
                f"command {runner.command!r} is not on PATH"
            )


def runner_for_role(role: str, root: Path) -> AgentRunner:
    """Construct the runner instance configured for a given role.

    Priority: per_role[<role>] override → default → "claude-code".
    Raises ValueError if the configured runner name is not registered;
    raises RuntimeError if the runner's CLI is not available on PATH.
    """
    cfg = load_runner_config(root)
    name = cfg.get("per_role", {}).get(role) or cfg.get("default") or "claude-code"
    if name not in _REGISTRY:
        raise ValueError(
            f"unknown runner {name!r} for role {role!r}; "
            f"registered: {sorted(_REGISTRY)}"
        )
    runner_cls = _REGISTRY[name]
    runner_cfg = cfg.get(name, {}) if isinstance(cfg.get(name), dict) else {}
    runner = runner_cls(runner_cfg)
    if not runner.is_available():
        raise RuntimeError(
            f"runner {name!r} is configured for role {role!r} but its "
            f"command {runner.command!r} is not on PATH"
        )
    return runner


def _tail(text: str, limit: int = DEFAULT_OUTPUT_TAIL_BYTES) -> str:
    if not text:
        return ""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return text
    return encoded[-limit:].decode("utf-8", errors="replace")
