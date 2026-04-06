#!/usr/bin/env python3
"""Copy a baseline/design folder into a new design folder and patch output_dir.

Usage:
    python scripts/tools/setup_design.py <src_folder> <dst_folder>
    python scripts/cli.py setup-design <src_folder> <dst_folder>

Example:
    python scripts/cli.py setup-design baseline/ runs/idea001/design001/

What it does:
  1. Copies all .py files from <src_folder> into <dst_folder>/code/ (creates it if needed).
  2. In the copied config.py, updates the output_dir class attribute to the
     absolute path of <dst_folder> (not code/) so training output lands in the design folder.
"""

import argparse
import csv
import re
import shutil
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.layout import parse_design_ref, resolve_code_dir  # noqa: E402
from scripts.lib.models import ALLOWED_BOOTSTRAP_SOURCE_STATUSES  # noqa: E402


def _read_design_status(repo_root: Path, idea_id: str, design_id: str):
    design_csv = repo_root / "runs" / idea_id / "design_overview.csv"
    if not design_csv.exists():
        raise SystemExit(f"Error: missing design overview CSV: {design_csv}")
    with design_csv.open("r", newline="", encoding="utf-8") as f:
        rows = csv.reader(f)
        next(rows, None)  # header
        for row in rows:
            if row and row[0] == design_id:
                return row[2] if len(row) > 2 else ""
    raise SystemExit(f"Error: {design_id} not found in {design_csv}")


def _validate_source_status(src: Path, repo_root: Path):
    """
    Enforce that design-to-design bootstrapping only uses implemented (or later) sources.
    baseline/ is always allowed.
    """
    ref = parse_design_ref(src)
    if not ref:
        return
    idea_id, design_id = ref
    status = _read_design_status(repo_root, idea_id, design_id)
    if status not in ALLOWED_BOOTSTRAP_SOURCE_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_BOOTSTRAP_SOURCE_STATUSES))
        raise SystemExit(
            "Error: source design is not implemented yet.\n"
            f"Source: runs/{idea_id}/{design_id}\n"
            f"Current status: {status}\n"
            f"Allowed statuses: {allowed}\n"
            "Pick baseline/ or an implemented design as the starting point."
        )


def setup_design(src: Path, dst: Path, root: Path | None = None) -> None:
    src = Path(src).resolve()
    dst = Path(dst).resolve()
    code_dir = dst / "code"
    repo_root = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[2]

    if not src.is_dir():
        raise SystemExit(f"Error: source folder not found: {src}")

    _validate_source_status(src, repo_root)

    # Source must have a code/ subfolder (unless it's the baseline, which is flat)
    src_code = resolve_code_dir(src)

    code_dir.mkdir(parents=True, exist_ok=True)

    # Copy all .py files from src (non-recursive — no test_output/ etc.)
    copied = []
    for f in sorted(src_code.glob("*.py")):
        shutil.copy2(f, code_dir / f.name)
        copied.append(f.name)

    if not copied:
        raise SystemExit(f"Error: no .py files found in {src_code}")

    print(f"Copied {len(copied)} file(s) from {src_code} → {code_dir}:")
    for name in copied:
        print(f"  {name}")

    # Patch output_dir in config.py to point to the design folder (not code/)
    config_path = code_dir / "config.py"
    if not config_path.exists():
        print("Warning: config.py not found in destination — output_dir not patched.")
        return

    text = config_path.read_text()
    new_text, n = re.subn(
        r'(output_dir\s*=\s*)["\'].*?["\']',
        rf'\g<1>"{dst}"',
        text,
    )

    if n == 0:
        print("Warning: output_dir not found in config.py — not patched.")
    else:
        config_path.write_text(new_text)
        print(f"Patched output_dir → \"{dst}\"")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("src", help="Source folder (e.g. baseline/ or runs/idea001/design002/)")
    parser.add_argument("dst", help="Destination design folder (e.g. runs/idea002/design001/)")
    args = parser.parse_args()
    setup_design(Path(args.src), Path(args.dst))


if __name__ == "__main__":
    main()
