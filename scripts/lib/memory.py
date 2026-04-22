"""Append structured mistake entries to agent memory files.

Each agent has its own `agents/<Agent>/memory.md` file that functions as
a persistent log of mistakes it has made. Entries follow a fixed format
so future agent invocations can skim them and avoid repetition:

    ## <ISO-date> — <title>
    **What I did:** ...
    **Why it was wrong:** ...
    **How to avoid:** ...
    **Source:** <who-caught-it>

The mistake log is append-only. Whoever *caught* the mistake writes to
the offending agent's memory file (script-driven catches write to
`Builder/memory.md` by default, since they fire on implementation-time
failures).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from scripts.lib import layout


HEADER = "# Builder Memory"  # default, only written if file is brand-new
MEMORY_FILENAME = "memory.md"


@dataclass(frozen=True)
class MistakeEntry:
    title: str
    what_i_did: str
    why_wrong: str
    how_to_avoid: str
    source: str

    def render(self, date: str | None = None) -> str:
        date = date or datetime.now().date().isoformat()
        return (
            f"\n## {date} — {self.title}\n"
            f"**What I did:** {self.what_i_did}\n"
            f"**Why it was wrong:** {self.why_wrong}\n"
            f"**How to avoid:** {self.how_to_avoid}\n"
            f"**Source:** {self.source}\n"
        )


def memory_path(agent: str, root: Path | None = None) -> Path:
    return layout.repo_root(root) / "agents" / agent / MEMORY_FILENAME


def append_mistake(agent: str, entry: MistakeEntry, root: Path | None = None) -> Path:
    path = memory_path(agent, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            f"# {agent} Memory\n\n"
            f"Structured log of mistakes the {agent} has made, kept so future "
            f"invocations can skim and avoid repetition.\n\n"
            "**Entry format (append new entries at the bottom):**\n\n"
            "```\n"
            "## <YYYY-MM-DD> — <one-line title>\n"
            "**What I did:** ...\n"
            "**Why it was wrong:** ...\n"
            "**How to avoid:** ...\n"
            "**Source:** <who caught it — Reviewer / scope_check / verify_claims / user>\n"
            "```\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.render())
    return path
