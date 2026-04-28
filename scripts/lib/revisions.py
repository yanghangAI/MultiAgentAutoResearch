"""Project-level revisions: cross-cutting changes that affect more than one design.

A revision is a logged, scoped edit to project axes that the integrity model
otherwise treats as frozen — `infra/`, `baseline/`, agent prompts, prior
designs, configuration. Each revision is one section in the top-level
`revisions.md` file and has:

- an id of the form `revNNN` (zero-padded, monotonic)
- a short name and ISO date
- a `Scope:` block listing the paths it touched
- a free-form body (Reason, Comparability note, etc.)

Designs are stamped with the latest revision id at the time their results
were first observed (`<design>/.revision`). A later revision with overlapping
scope can mark such a design `stale` — distinct from `tainted`: results are
still kept, but flagged as produced under an older project state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from scripts.lib import layout, scope as scope_mod, store


REVISIONS_FILENAME = "revisions.md"
DESIGN_REVISION_FILENAME = ".revision"
REV_ID_RE = re.compile(r"^rev\d{3}$")
_HEADER_RE = re.compile(
    r"^##\s+(rev\d{3})\s*[—-]\s*(\d{4}-\d{2}-\d{2})\s*[—-]\s*(.+?)\s*$"
)


@dataclass(frozen=True)
class Revision:
    id: str
    date: str
    name: str
    scope: tuple[str, ...] = ()
    body: str = ""


def revisions_md_path(root: Path | None = None) -> Path:
    return layout.repo_root(root) / REVISIONS_FILENAME


def _parse_scope_block(lines: list[str]) -> list[str]:
    """Extract bullet entries from a `**Scope:**` block until blank or next header."""
    scope_paths: list[str] = []
    in_block = False
    for raw in lines:
        stripped = raw.strip()
        if not in_block:
            if stripped.startswith("**Scope:**"):
                in_block = True
                trailing = stripped[len("**Scope:**"):].strip()
                if trailing:
                    scope_paths.extend(_split_inline_paths(trailing))
            continue
        if not stripped:
            break
        if stripped.startswith("**") and stripped.endswith(":**"):
            break
        if stripped.startswith(("- ", "* ")):
            stripped = stripped[2:]
        for sep in ("  # ", " — ", " - "):
            if sep in stripped:
                stripped = stripped.split(sep, 1)[0]
        stripped = stripped.strip().strip("`").strip()
        if stripped:
            scope_paths.append(stripped)
    return scope_paths


def _split_inline_paths(text: str) -> list[str]:
    parts = [p.strip().strip("`") for p in re.split(r"[,;]", text)]
    return [p for p in parts if p]


def parse_revisions(root: Path | None = None) -> list[Revision]:
    """Parse `revisions.md`. Returns revisions in file order (chronological)."""
    path = revisions_md_path(root)
    text = store.read_text(path)
    if not text:
        return []
    lines = text.splitlines()
    revisions: list[Revision] = []
    cur_id: str | None = None
    cur_date: str = ""
    cur_name: str = ""
    cur_lines: list[str] = []

    def flush() -> None:
        if cur_id is None:
            return
        scope = _parse_scope_block(cur_lines)
        body = "\n".join(cur_lines).strip()
        revisions.append(
            Revision(
                id=cur_id,
                date=cur_date,
                name=cur_name,
                scope=tuple(scope),
                body=body,
            )
        )

    for raw in lines:
        m = _HEADER_RE.match(raw)
        if m:
            flush()
            cur_id, cur_date, cur_name = m.group(1), m.group(2), m.group(3).strip()
            cur_lines = []
        else:
            if cur_id is not None:
                cur_lines.append(raw)
    flush()
    return revisions


def current_revision_id(root: Path | None = None) -> str | None:
    revs = parse_revisions(root)
    if not revs:
        return None
    return revs[-1].id


def next_revision_id(root: Path | None = None) -> str:
    revs = parse_revisions(root)
    if not revs:
        return "rev001"
    last = revs[-1].id
    n = int(last[3:]) + 1
    return f"rev{n:03d}"


def design_revision(design_dir: Path) -> str | None:
    """Read the `.revision` stamp for a design, or None if unstamped."""
    path = Path(design_dir) / DESIGN_REVISION_FILENAME
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def stamp_design_revision(design_dir: Path, rev_id: str | None) -> None:
    """Write `.revision` if not already stamped. No-op if rev_id is None.

    The stamp is written-once: it captures the project state at the time
    results first appeared, and must survive subsequent revisions.
    """
    if rev_id is None:
        return
    design_dir = Path(design_dir)
    target = design_dir / DESIGN_REVISION_FILENAME
    if target.exists():
        return
    design_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{rev_id}\n", encoding="utf-8")


def _scope_overlaps_design(
    scope_paths: tuple[str, ...],
    design_rel: str,
    lineage_includes_baseline: bool,
) -> bool:
    """Decide whether a revision's scope invalidates a design's results.

    Triggers staleness:
    - scope touches infra/ (always invalidates results)
    - scope touches baseline/ and design's lineage includes baseline
    - scope path matches the design's own runs/<idea>/<design>/ subtree
    Prompt edits and other agent-file changes do NOT trigger staleness —
    they affect future decisions, not past metrics.
    """
    for raw in scope_paths:
        p = raw.replace("\\", "/").lstrip("./").strip("/")
        if not p:
            continue
        if p.startswith("infra/") or p == "infra":
            return True
        if lineage_includes_baseline and (p.startswith("baseline/") or p == "baseline"):
            return True
        if p.startswith(design_rel + "/") or p == design_rel:
            return True
    return False


def staling_revisions(
    design_dir: Path,
    root: Path | None = None,
    revisions: list[Revision] | None = None,
) -> list[str]:
    """Return ids of revisions that stale this design (empty if none)."""
    if revisions is None:
        revisions = parse_revisions(root)
    if not revisions:
        return []
    stamp = design_revision(design_dir)
    # If no stamp, the design predates the revision system and we can't
    # reason about which revisions are "later" — leave it alone.
    if stamp is None:
        return []
    rev_index = {r.id: i for i, r in enumerate(revisions)}
    stamp_idx = rev_index.get(stamp)
    if stamp_idx is None:
        # Stamp references a revision we don't know about — can't compare.
        return []

    root_path = layout.repo_root(root)
    design_dir = Path(design_dir).resolve()
    try:
        design_rel = design_dir.relative_to(root_path).as_posix()
    except ValueError:
        design_rel = ""

    lineage = scope_mod.walk_lineage(design_dir, root=root_path)
    baseline = (root_path / "baseline").resolve()
    lineage_includes_baseline = any(p.resolve() == baseline for p in lineage if p.exists())

    out: list[str] = []
    for later in revisions[stamp_idx + 1:]:
        if _scope_overlaps_design(later.scope, design_rel, lineage_includes_baseline):
            out.append(later.id)
    return out
