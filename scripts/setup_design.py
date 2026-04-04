#!/usr/bin/env python3
"""Copy a baseline/design folder into a new design folder and patch output_dir.

Usage:
    python scripts/setup_design.py <src_folder> <dst_folder>

Example:
    python scripts/setup_design.py baseline/ runs/idea001/design001/

What it does:
  1. Copies all .py files from <src_folder> into <dst_folder>/code/ (creates it if needed).
  2. In the copied config.py, updates the output_dir class attribute to the
     absolute path of <dst_folder> (not code/) so training output lands in the design folder.
"""

import argparse
import csv
import re
import shutil
from pathlib import Path


ALLOWED_SOURCE_STATUSES = {"Implemented", "Training", "Done"}


def _parse_design_ref(path: Path):
    """
    Return (idea_id, design_id) if path looks like runs/<idea_id>/<design_id>[/code], else None.
    """
    parts = path.parts
    for i, p in enumerate(parts):
        if p == "runs" and i + 2 < len(parts):
            idea_id = parts[i + 1]
            design_id = parts[i + 2]
            if idea_id.startswith("idea") and design_id.startswith("design"):
                return idea_id, design_id
    return None


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
    ref = _parse_design_ref(src)
    if not ref:
        return
    idea_id, design_id = ref
    status = _read_design_status(repo_root, idea_id, design_id)
    if status not in ALLOWED_SOURCE_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_SOURCE_STATUSES))
        raise SystemExit(
            "Error: source design is not implemented yet.\n"
            f"Source: runs/{idea_id}/{design_id}\n"
            f"Current status: {status}\n"
            f"Allowed statuses: {allowed}\n"
            "Pick baseline/ or an implemented design as the starting point."
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("src", help="Source folder (e.g. baseline/ or runs/idea001/design002/)")
    parser.add_argument("dst", help="Destination design folder (e.g. runs/idea002/design001/)")
    args = parser.parse_args()

    src = Path(args.src).resolve()
    dst = Path(args.dst).resolve()
    code_dir = dst / "code"
    repo_root = Path(__file__).resolve().parents[1]

    if not src.is_dir():
        raise SystemExit(f"Error: source folder not found: {src}")

    _validate_source_status(src, repo_root)

    # Source must have a code/ subfolder (unless it's the baseline, which is flat)
    src_code = src / "code" if (src / "code").is_dir() else src

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


if __name__ == "__main__":
    main()
