"""begin-revision / finalize-revision CLI flow.

Cross-cutting changes (touching infra/, baseline/, prompts, prior designs,
config) bypass the normal design integrity model. These commands gate them:

- `begin-revision <short-name>` allocates the next `revNNN` id, refuses if
  there are in-flight designs (Submitted/Training), tags the current git
  HEAD as `pre-revNNN`, and writes a skeleton section into `revisions.md`
  for the Reviser agent to fill in.

- `finalize-revision` validates the latest section in `revisions.md` has a
  `**Scope:**` block + reason, then runs `sync-status` to propagate the
  staleness flag onto affected prior designs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.lib import layout, revisions as revisions_mod, store
from scripts.lib.context import ProjectContext
from scripts.lib.models import Status


_IN_FLIGHT = {Status.SUBMITTED, Status.TRAINING, Status.SUBMISSION_STALE}


def _git(args: list[str], root: Path) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return 127, ""
    return result.returncode, (result.stdout + result.stderr).strip()


def _working_tree_clean(root: Path) -> bool:
    rc, out = _git(["status", "--porcelain"], root)
    return rc == 0 and out == ""


def _in_flight_designs(ctx: ProjectContext) -> list[str]:
    out: list[str] = []
    runs = layout.runs_dir(ctx.root)
    if not runs.is_dir():
        return out
    for csv_path in sorted(runs.glob("idea*/design_overview.csv")):
        for row in store.read_dict_rows(csv_path):
            status = row.get("Status", "")
            if status in _IN_FLIGHT:
                idea_id = csv_path.parent.name
                out.append(f"{idea_id}/{row.get('Design_ID', '?')} ({status})")
    return out


def _append_skeleton(rev_id: str, name: str, root: Path) -> None:
    from datetime import date as _date

    path = revisions_mod.revisions_md_path(root)
    today = _date.today().isoformat()
    section = (
        f"\n## {rev_id} — {today} — {name}\n"
        f"**Author:** Reviser agent\n"
        f"**Scope:**\n"
        f"- <path touched, one per line>\n"
        f"\n"
        f"**Reason:** <why this change is needed>\n"
        f"\n"
        f"**Comparability note:** <how prior results compare to post-revision results>\n"
    )
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if not existing.endswith("\n"):
            existing += "\n"
        path.write_text(existing + section, encoding="utf-8")
    else:
        header = "# Project Revisions\n\nCross-cutting changes to infra, baseline, prompts, or prior designs.\n"
        path.write_text(header + section, encoding="utf-8")


def begin_revision(name: str, ctx: ProjectContext, allow_dirty: bool = False) -> int:
    root = ctx.root
    if not name.strip():
        print("revision name must not be empty.")
        return 2

    if not allow_dirty and not _working_tree_clean(root):
        print(
            "working tree has uncommitted changes. Commit or stash first, "
            "or pass --allow-dirty if you know what you're doing."
        )
        return 2

    in_flight = _in_flight_designs(ctx)
    if in_flight:
        print("refusing to start a revision while designs are in flight:")
        for entry in in_flight:
            print(f"  - {entry}")
        print("wait for them to finish or fail before starting a revision.")
        return 2

    rev_id = revisions_mod.next_revision_id(root)
    tag = f"pre-{rev_id}"
    rc, msg = _git(["tag", tag], root)
    if rc != 0:
        # Non-fatal: tagging is a recovery aid, not load-bearing.
        print(f"warning: could not tag git HEAD as {tag} ({msg or 'git unavailable'}).")
    else:
        print(f"tagged git HEAD as {tag}.")

    _append_skeleton(rev_id, name.strip(), root)
    print(f"started {rev_id}: '{name}'.")
    print(f"  - edit {revisions_mod.revisions_md_path(root)} to fill in Scope and Reason.")
    print(f"  - make your edits to infra/, baseline/, prompts, etc.")
    print(f"  - run `python scripts/cli.py finalize-revision` when done.")
    return 0


def finalize_revision(ctx: ProjectContext) -> int:
    root = ctx.root
    revs = revisions_mod.parse_revisions(root)
    if not revs:
        print("no revisions found in revisions.md. Run `begin-revision` first.")
        return 2

    latest = revs[-1]
    issues: list[str] = []
    if not latest.scope:
        issues.append("missing **Scope:** entries (or all entries are placeholders).")
    placeholder_markers = ("<path touched", "<why this change", "<how prior results")
    for marker in placeholder_markers:
        if marker in latest.body:
            issues.append(f"placeholder text still present: {marker!r}")
    cleaned_scope = [s for s in latest.scope if not s.startswith("<")]
    if not cleaned_scope:
        issues.append("**Scope:** contains only placeholder entries.")

    if issues:
        print(f"cannot finalize {latest.id}:")
        for issue in issues:
            print(f"  - {issue}")
        return 2

    print(f"finalized {latest.id} — '{latest.name}'.")
    print(f"  scope: {', '.join(cleaned_scope)}")
    print("running sync-status to propagate staleness...")
    # Local import to avoid circular import at module load time.
    from scripts.lib import status as status_mod

    status_mod.sync_all(ctx)
    return 0
