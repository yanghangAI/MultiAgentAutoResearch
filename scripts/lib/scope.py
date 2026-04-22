"""Parent tracking, scope checks, and lineage for designs.

A design directory may contain a `.parent` file whose single line is the
absolute path of the source that `setup-design` bootstrapped from — either
`baseline/` or another design's root (e.g. `runs/ideaNNN/designMMM`).

`check_scope` verifies two invariants on a design:

1. **Declared-scope check** — every file under `<design>/code/` that differs
   from the declared parent's code tree must appear in the
   `**Files changed:**` section of `implementation_summary.md`.
2. **Immutable check** — every file under `<design>/code/` whose relative
   path matches any glob in `integrity.immutable_paths` must be byte-identical
   to the corresponding file in `baseline/` (or absent from both).

Results are written as `scope_check.pass` or `scope_check.fail` at the
design directory root, and stdout carries a human-readable summary.
"""

from __future__ import annotations

import fnmatch
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from scripts.lib import layout, store
from scripts.lib.project_config import load_project_config


PARENT_FILENAME = ".parent"
SCOPE_PASS = "scope_check.pass"
SCOPE_FAIL = "scope_check.fail"


@dataclass
class ScopeReport:
    passed: bool
    undeclared_changes: list[str] = field(default_factory=list)
    missing_declared_changes: list[str] = field(default_factory=list)
    immutable_violations: list[str] = field(default_factory=list)
    parent_path: str = ""
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [f"parent: {self.parent_path}"]
        if self.undeclared_changes:
            lines.append("undeclared changes (not in implementation_summary.md):")
            lines.extend(f"  - {p}" for p in self.undeclared_changes)
        if self.missing_declared_changes:
            lines.append("declared files with no actual change vs parent:")
            lines.extend(f"  - {p}" for p in self.missing_declared_changes)
        if self.immutable_violations:
            lines.append("immutable-path violations (differ from baseline):")
            lines.extend(f"  - {p}" for p in self.immutable_violations)
        if self.notes:
            lines.append("notes:")
            lines.extend(f"  - {n}" for n in self.notes)
        lines.append("result: PASS" if self.passed else "result: FAIL")
        return "\n".join(lines) + "\n"


def read_parent(design_dir: Path) -> Path | None:
    parent_file = design_dir / PARENT_FILENAME
    if not parent_file.exists():
        return None
    text = parent_file.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return Path(text)


def write_parent(design_dir: Path, src: Path) -> None:
    design_dir.mkdir(parents=True, exist_ok=True)
    (design_dir / PARENT_FILENAME).write_text(f"{Path(src).resolve()}\n", encoding="utf-8")


def has_scope_pass(design_dir: Path) -> bool:
    return (design_dir / SCOPE_PASS).exists()


def has_scope_fail(design_dir: Path) -> bool:
    return (design_dir / SCOPE_FAIL).exists()


def is_tainted(design_dir: Path, root: Path | None = None) -> bool:
    """True if this design, or any ancestor via `.parent`, has scope_check.fail.

    An ancestor without any scope marker at all is treated as unknown, not
    tainted — it's the job of setup-design to refuse unchecked parents, so
    unmarked links in the chain either mean the design predates PR 1 or is
    baseline itself. Cycles are defensively terminated.
    """
    root_path = layout.repo_root(root)
    current = Path(design_dir).resolve()
    visited: set[Path] = set()
    while True:
        if current in visited:
            return False
        visited.add(current)
        if has_scope_fail(current):
            return True
        if _is_baseline(current, root_path):
            return False
        parent_raw = read_parent(current)
        if parent_raw is None:
            return False
        current = parent_raw.resolve()


def _baseline_dir(root: Path) -> Path:
    return (root / "baseline").resolve()


def _is_baseline(path: Path, root: Path) -> bool:
    try:
        return Path(path).resolve() == _baseline_dir(root)
    except OSError:
        return False


def _matches_any_glob(rel_path: str, globs: tuple[str, ...]) -> bool:
    for pat in globs:
        if fnmatch.fnmatch(rel_path, pat):
            return True
        # `**` support: fnmatch doesn't treat ** specially — extend manually.
        if "**" in pat:
            simple = pat.replace("**", "*")
            if fnmatch.fnmatch(rel_path, simple):
                return True
            # Prefix match: "infra/**" should match "infra/x/y.py"
            prefix = pat.split("**", 1)[0].rstrip("/")
            if prefix and (rel_path == prefix or rel_path.startswith(prefix + "/")):
                return True
    return False


def _walk_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file())


def _file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_declared_files(summary_path: Path) -> list[str]:
    """Extract file paths from the `**Files changed:**` block of implementation_summary.md.

    Any line after the header until a blank line or next bold header is considered.
    Paths are extracted as:
      - leading `- ` or `* ` bullet stripped
      - surrounding backticks stripped
      - text before the first ` - ` or ` — ` description delimiter kept
    """
    if not summary_path.exists():
        return []
    text = store.read_text(summary_path)
    lines = text.splitlines()
    declared: list[str] = []
    in_block = False
    for raw in lines:
        line = raw.rstrip()
        stripped = line.lstrip()
        if not in_block:
            if stripped.startswith("**Files changed:**"):
                in_block = True
                trailing = stripped[len("**Files changed:**"):].strip()
                if trailing:
                    declared.extend(_split_inline_list(trailing))
            continue
        # In block: stop on blank line or another bold header
        if not stripped:
            break
        if stripped.startswith("**") and stripped.endswith(":**"):
            break
        # Bullet or plain line — extract path
        if stripped.startswith(("- ", "* ")):
            stripped = stripped[2:]
        # Strip description after ' - ' or ' — '
        for sep in (" - ", " — ", ": "):
            if sep in stripped:
                stripped = stripped.split(sep, 1)[0]
        stripped = stripped.strip().strip("`").strip()
        if stripped:
            declared.append(stripped)
    return declared


def _split_inline_list(text: str) -> list[str]:
    parts = [p.strip().strip("`") for p in text.replace(";", ",").split(",")]
    return [p for p in parts if p]


def _normalize_declared(declared: list[str], code_dir_name: str) -> set[str]:
    """Normalize declared paths so they are relative to the design's code/ dir.

    Accepts forms like:
      - `code/foo/bar.py`          → `foo/bar.py`
      - `runs/ideaNNN/designMMM/code/foo.py` → `foo.py`
      - `foo/bar.py`               → `foo/bar.py`
    """
    out: set[str] = set()
    for p in declared:
        norm = p.replace("\\", "/").strip("/")
        if f"/{code_dir_name}/" in norm:
            norm = norm.split(f"/{code_dir_name}/", 1)[1]
        elif norm.startswith(f"{code_dir_name}/"):
            norm = norm[len(code_dir_name) + 1:]
        out.add(norm)
    return out


def _resolve_parent_code(parent_path: Path, root: Path) -> Path:
    """Return the code directory for a parent. Baseline is flat; designs have code/."""
    if _is_baseline(parent_path, root):
        return _baseline_dir(root)
    candidate = parent_path / "code"
    if candidate.is_dir():
        return candidate
    return parent_path


def check_scope(design_dir: Path, root: Path | None = None) -> ScopeReport:
    root_path = layout.repo_root(root)
    design_dir = Path(design_dir).resolve()
    cfg = load_project_config(root_path)
    code_subdir = cfg.setup_design.destination_subdir
    code_dir = design_dir / code_subdir

    if not code_dir.is_dir():
        report = ScopeReport(passed=False, parent_path="")
        report.notes.append(f"design code dir not found: {code_dir}")
        return report

    parent_raw = read_parent(design_dir)
    if parent_raw is None:
        report = ScopeReport(passed=False, parent_path="")
        report.notes.append(
            f"missing {PARENT_FILENAME} — re-run `setup-design` or write the parent path manually."
        )
        return report
    parent_path = parent_raw.resolve()
    report = ScopeReport(passed=True, parent_path=str(parent_path))

    parent_code = _resolve_parent_code(parent_path, root_path)
    if not parent_code.is_dir():
        report.passed = False
        report.notes.append(f"parent code dir not found: {parent_code}")
        return report

    # If parent is a design (not baseline) it must have scope_check.pass.
    if not _is_baseline(parent_path, root_path) and not has_scope_pass(parent_path):
        report.passed = False
        report.notes.append(
            f"parent design has no {SCOPE_PASS} marker: {parent_path}. "
            "Run `check-scope` on the parent first."
        )

    baseline_dir = _baseline_dir(root_path)
    immutable_globs = tuple(cfg.integrity.immutable_paths)

    # 1. Diff design/code against parent's code dir.
    design_files = _walk_files(code_dir)
    parent_files = _walk_files(parent_code)
    design_rel = {p.relative_to(code_dir).as_posix() for p in design_files}
    parent_rel = {p.relative_to(parent_code).as_posix() for p in parent_files}
    changed: set[str] = set()
    for rel in design_rel | parent_rel:
        dh = _file_hash(code_dir / rel)
        ph = _file_hash(parent_code / rel)
        if dh != ph:
            changed.add(rel)

    summary_path = design_dir / "implementation_summary.md"
    declared_raw = _parse_declared_files(summary_path)
    declared = _normalize_declared(declared_raw, code_subdir)

    undeclared = sorted(changed - declared)
    missing_declared = sorted(declared - changed)
    if undeclared:
        report.passed = False
        report.undeclared_changes = undeclared
    if missing_declared:
        # Not fatal — Builder may list files it planned to change but didn't
        # need to. Record for review, don't fail.
        report.missing_declared_changes = missing_declared

    # 2. Immutable check: each design file matching an immutable glob must
    #    equal the baseline file (or both must be absent).
    if immutable_globs:
        immutable_violations: list[str] = []
        baseline_files = {p.relative_to(baseline_dir).as_posix(): p for p in _walk_files(baseline_dir)}
        candidates = set(design_rel) | set(baseline_files.keys())
        for rel in sorted(candidates):
            if not _matches_any_glob(rel, immutable_globs):
                continue
            dh = _file_hash(code_dir / rel)
            bh = _file_hash(baseline_files.get(rel, Path("/nonexistent")))
            if dh != bh:
                immutable_violations.append(rel)
        if immutable_violations:
            report.passed = False
            report.immutable_violations = immutable_violations

    return report


def run_check_scope(design_dir: Path, root: Path | None = None) -> int:
    root_path = layout.repo_root(root)
    design_dir = Path(design_dir)
    if not design_dir.is_absolute():
        design_dir = (root_path / design_dir).resolve()
    else:
        design_dir = design_dir.resolve()

    report = check_scope(design_dir, root=root_path)
    rendered = report.render()
    print(rendered, end="")

    # Clean any prior marker, then write the fresh one.
    (design_dir / SCOPE_PASS).unlink(missing_ok=True)
    (design_dir / SCOPE_FAIL).unlink(missing_ok=True)
    marker = SCOPE_PASS if report.passed else SCOPE_FAIL
    (design_dir / marker).write_text(rendered, encoding="utf-8")
    return 0 if report.passed else 1


def walk_lineage(design_dir: Path, root: Path | None = None) -> list[Path]:
    """Return the ancestor chain from the given design up to baseline (or a dead end).

    The first element is the design itself. Each subsequent element is the parent
    referenced by the previous one's `.parent` file (or its resolved code dir's
    containing design dir for baseline).
    """
    root_path = layout.repo_root(root)
    design_dir = Path(design_dir).resolve()
    chain: list[Path] = [design_dir]
    visited = {design_dir}
    current = design_dir
    while True:
        parent_raw = read_parent(current)
        if parent_raw is None:
            break
        parent = parent_raw.resolve()
        chain.append(parent)
        if _is_baseline(parent, root_path):
            break
        if parent in visited:
            chain.append(Path(f"<cycle detected at {parent}>"))
            break
        visited.add(parent)
        current = parent
    return chain


def run_lineage(design_dir: Path, root: Path | None = None) -> int:
    chain = walk_lineage(design_dir, root=root)
    for i, p in enumerate(chain):
        prefix = "→ " if i > 0 else "  "
        print(f"{prefix}{p}")
    return 0
