"""Verify that code snippets quoted in `implementation_summary.md` are
actually present in the files they claim to change.

The Builder's summary is treated as a set of claims. For each fenced code
block we attribute it to a file (by scanning up to 5 non-blank lines above
the opening fence for a path-like token) and confirm, after normalizing
whitespace, that the snippet appears as a substring of that file's current
contents.

Design philosophy: catch outright fabrication, not formatting drift.
Whitespace is collapsed on both sides before matching.

Behavior matrix:
  * No fenced blocks at all           → pass (nothing to verify).
  * Unattributed block                → warning, skipped (not a failure).
  * Attributed but file missing       → fail.
  * Attributed, file exists, no match → fail with an excerpt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from scripts.lib import layout, store
from scripts.lib.project_config import load_project_config


_FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
_PATH_TOKEN_RE = re.compile(r"`([A-Za-z0-9_./\-]+\.[A-Za-z0-9_]+)`")


@dataclass
class ClaimsReport:
    passed: bool
    missing: list[tuple[str, str]] = field(default_factory=list)  # (file, excerpt)
    unattributed: list[str] = field(default_factory=list)  # excerpts
    notes: list[str] = field(default_factory=list)
    checked: int = 0

    def render(self) -> str:
        lines = [f"snippets checked: {self.checked}"]
        if self.unattributed:
            lines.append("unattributed snippets (no preceding file reference — skipped):")
            for ex in self.unattributed:
                lines.append(f"  - {ex!r}")
        if self.missing:
            lines.append("claims not found in their referenced files:")
            for f, ex in self.missing:
                lines.append(f"  - {f}: {ex!r}")
        if self.notes:
            lines.append("notes:")
            lines.extend(f"  - {n}" for n in self.notes)
        lines.append("result: PASS" if self.passed else "result: FAIL")
        return "\n".join(lines) + "\n"


def _parse_fenced_blocks(text: str) -> list[tuple[list[str], str]]:
    """Return a list of (preceding_context_lines, block_body) tuples.

    preceding_context_lines is up to 5 non-blank lines immediately above the
    opening fence, in original order (oldest first).
    """
    lines = text.splitlines()
    blocks: list[tuple[list[str], str]] = []
    i = 0
    while i < len(lines):
        m = _FENCE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        fence_token = m.group(2)
        # Gather preceding context: up to 5 non-blank lines above.
        context: list[str] = []
        j = i - 1
        while j >= 0 and len(context) < 5:
            candidate = lines[j]
            if candidate.strip():
                context.append(candidate)
            else:
                if context:  # stop at blank once we have anything
                    break
            j -= 1
        context.reverse()

        # Collect body lines until a matching closing fence.
        body_lines: list[str] = []
        k = i + 1
        closed = False
        while k < len(lines):
            closing = _FENCE_RE.match(lines[k])
            if closing and closing.group(2).startswith(fence_token[0]) and len(closing.group(2)) >= len(fence_token):
                closed = True
                break
            body_lines.append(lines[k])
            k += 1
        if closed:
            blocks.append((context, "\n".join(body_lines)))
            i = k + 1
        else:
            i = k
    return blocks


def _attribute_block(context: list[str]) -> str | None:
    """Return the last path-like token found anywhere in the context lines, or None."""
    last: str | None = None
    for line in context:
        for match in _PATH_TOKEN_RE.finditer(line):
            last = match.group(1)
    return last


def _normalize(text: str) -> str:
    # Collapse any whitespace run to a single space, strip ends.
    return re.sub(r"\s+", " ", text).strip()


def _resolve_claimed_file(rel: str, design_dir: Path, code_subdir: str) -> Path:
    """Resolve a claimed relative path to an actual filesystem path under the design.

    Accepted forms (same as scope declared-paths normalization):
      - `code/foo/bar.py`          → design_dir/code/foo/bar.py
      - `runs/.../code/foo.py`     → design_dir/code/foo.py (anchor on code/)
      - `foo/bar.py`               → design_dir/code/foo/bar.py
    """
    norm = rel.replace("\\", "/").strip("/")
    if f"/{code_subdir}/" in norm:
        norm = norm.split(f"/{code_subdir}/", 1)[1]
    elif norm.startswith(f"{code_subdir}/"):
        norm = norm[len(code_subdir) + 1:]
    return design_dir / code_subdir / norm


def verify_claims(design_dir: Path, root: Path | None = None) -> ClaimsReport:
    root_path = layout.repo_root(root)
    design_dir = Path(design_dir).resolve()
    cfg = load_project_config(root_path)
    code_subdir = cfg.setup_design.destination_subdir

    summary_path = design_dir / "implementation_summary.md"
    if not summary_path.exists():
        return ClaimsReport(
            passed=False,
            notes=[f"missing {summary_path}"],
        )

    text = store.read_text(summary_path)
    blocks = _parse_fenced_blocks(text)
    report = ClaimsReport(passed=True, checked=0)

    if not blocks:
        report.notes.append("no fenced code blocks found — nothing to verify.")
        return report

    for context, body in blocks:
        body_norm = _normalize(body)
        if not body_norm:
            continue
        claimed = _attribute_block(context)
        excerpt = body_norm[:80] + ("…" if len(body_norm) > 80 else "")
        if claimed is None:
            report.unattributed.append(excerpt)
            continue
        report.checked += 1
        target = _resolve_claimed_file(claimed, design_dir, code_subdir)
        if not target.is_file():
            report.passed = False
            report.missing.append((claimed, f"[file not found] {excerpt}"))
            continue
        file_norm = _normalize(target.read_text(encoding="utf-8", errors="replace"))
        if body_norm not in file_norm:
            report.passed = False
            report.missing.append((claimed, excerpt))

    return report


def run_verify_claims(design_dir: Path, root: Path | None = None) -> int:
    root_path = layout.repo_root(root)
    design_dir = Path(design_dir)
    if not design_dir.is_absolute():
        design_dir = (root_path / design_dir).resolve()
    else:
        design_dir = design_dir.resolve()
    report = verify_claims(design_dir, root=root_path)
    print(report.render(), end="")
    return 0 if report.passed else 1
