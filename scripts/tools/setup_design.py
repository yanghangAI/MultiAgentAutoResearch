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
import re
import shutil
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import scope, store  # noqa: E402
from scripts.lib.layout import design_csv_path, parse_design_ref, resolve_code_dir  # noqa: E402
from scripts.lib.models import ALLOWED_BOOTSTRAP_SOURCE_STATUSES  # noqa: E402
from scripts.lib.project_config import load_project_config  # noqa: E402


def _validate_source_status(src: Path, repo_root: Path) -> None:
    """
    Enforce that design-to-design bootstrapping only uses implemented (or later) sources.
    baseline/ is always allowed.
    """
    ref = parse_design_ref(src)
    if not ref:
        return
    idea_id, design_id = ref
    csv_path = design_csv_path(idea_id, root=repo_root)
    if not csv_path.exists():
        raise SystemExit(f"Error: missing design overview CSV: {csv_path}")
    rows = store.read_dict_rows(csv_path)
    matched = next((row for row in rows if row.get("Design_ID") == design_id), None)
    if matched is None:
        raise SystemExit(f"Error: {design_id} not found in {csv_path}")
    status = matched.get("Status", "")
    if status not in ALLOWED_BOOTSTRAP_SOURCE_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_BOOTSTRAP_SOURCE_STATUSES))
        raise SystemExit(
            "Error: source design is not implemented yet.\n"
            f"Source: runs/{idea_id}/{design_id}\n"
            f"Current status: {status}\n"
            f"Allowed statuses: {allowed}\n"
            "Pick baseline/ or an implemented design as the starting point."
        )


def _validate_source_scope_pass(src: Path) -> None:
    """Design-to-design bootstrapping requires the source to have passed check-scope.

    Baseline is exempt. This prevents laundering undetected modifications through
    intermediate designs.
    """
    if parse_design_ref(src) is None:
        return  # baseline or non-design source
    if not scope.has_scope_pass(src):
        raise SystemExit(
            f"Error: source design has no {scope.SCOPE_PASS} marker: {src}\n"
            f"Run `python scripts/cli.py check-scope {src}` first, resolve any "
            f"failures, then retry."
        )


def setup_design(src: Path, dst: Path, root: Path | None = None) -> None:
    src = Path(src).resolve()
    dst = Path(dst).resolve()
    repo_root = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[2]
    cfg = load_project_config(repo_root)
    code_dir = dst / cfg.setup_design.destination_subdir

    if not src.is_dir():
        raise SystemExit(f"Error: source folder not found: {src}")

    _validate_source_status(src, repo_root)
    _validate_source_scope_pass(src)

    # Source must have a code/ subfolder (unless it's the baseline, which is flat)
    src_code = resolve_code_dir(src)

    code_dir.mkdir(parents=True, exist_ok=True)

    # Copy configured file patterns from src (non-recursive — no test_output/ etc.)
    copied = []
    seen: set[Path] = set()
    for pattern in cfg.setup_design.source_globs:
        for f in sorted(src_code.glob(pattern)):
            if not f.is_file() or f in seen:
                continue
            shutil.copy2(f, code_dir / f.name)
            copied.append(f.name)
            seen.add(f)

    if not copied:
        raise SystemExit(
            f"Error: no matching source files found in {src_code} for patterns "
            f"{list(cfg.setup_design.source_globs)}"
        )

    scope.write_parent(dst, src)
    print(f"Recorded parent: {dst / scope.PARENT_FILENAME} → {src}")
    print(f"Copied {len(copied)} file(s) from {src_code} → {code_dir}:")
    for name in copied:
        print(f"  {name}")

    patch_cfg = cfg.setup_design.output_patch
    if not patch_cfg.enabled:
        return

    # Optional patch hook for destination-specific output directory.
    config_path = code_dir / patch_cfg.target_file
    if not config_path.exists():
        print(f"Warning: {patch_cfg.target_file} not found in destination — output patch skipped.")
        return

    text = config_path.read_text()
    new_text, n = re.subn(
        patch_cfg.regex,
        patch_cfg.replacement_template.format(dst=str(dst)),
        text,
    )

    if n == 0:
        print(f"Warning: output pattern not found in {patch_cfg.target_file} — patch skipped.")
    else:
        config_path.write_text(new_text)
        print(f"Patched output path target in {patch_cfg.target_file} → \"{dst}\"")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("src", help="Source folder (e.g. baseline/ or runs/idea001/design002/)")
    parser.add_argument("dst", help="Destination design folder (e.g. runs/idea002/design001/)")
    args = parser.parse_args()
    setup_design(Path(args.src), Path(args.dst))


if __name__ == "__main__":
    main()
