from __future__ import annotations

import re
from pathlib import Path

from scripts.lib import layout, store


def _parse_bold_field(content: str, field_name: str) -> str | None:
    pattern = rf"\*\*{re.escape(field_name)}:\*\*\s*(.+)"
    match = re.search(pattern, content)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _resolve_target(target: Path, root: Path | None = None) -> tuple[str, Path]:
    root_path = layout.repo_root(root)
    resolved = target if target.is_absolute() else (root_path / target)
    resolved = resolved.resolve()
    if resolved.is_dir():
        idea_md = resolved / "idea.md"
        design_md = resolved / "design.md"
        if idea_md.is_file():
            return "idea", idea_md
        if design_md.is_file():
            return "design", design_md
    if resolved.name == "idea.md":
        return "idea", resolved
    if resolved.name == "design.md":
        return "design", resolved
    raise SystemExit(f"Could not infer review target from {target}. Point to an idea/design folder or markdown file.")


def _check_idea(path: Path) -> list[str]:
    content = store.read_text(path)
    errors: list[str] = []
    if not content:
        return [f"Missing file: {path}"]
    if not _parse_bold_field(content, "Idea Name"):
        errors.append("Missing required field `**Idea Name:**`.")
    expected_designs = _parse_bold_field(content, "Expected Designs")
    if not expected_designs:
        errors.append("Missing required field `**Expected Designs:**`.")
    elif not expected_designs.isdigit() or int(expected_designs) <= 0:
        errors.append("`**Expected Designs:**` must be a positive integer.")
    if not _parse_bold_field(content, "Baseline Source"):
        errors.append("Missing required field `**Baseline Source:**`.")
    return errors


def _check_design(path: Path) -> list[str]:
    content = store.read_text(path)
    errors: list[str] = []
    if not content:
        return [f"Missing file: {path}"]
    if not _parse_bold_field(content, "Design Description"):
        errors.append("Missing required field `**Design Description:**`.")
    if not _parse_bold_field(content, "Starting Point"):
        errors.append("Missing required field `**Starting Point:**`.")
    required_phrases = (
        "config",
        "algorithm",
        "file",
    )
    lower_content = content.lower()
    for phrase in required_phrases:
        if phrase not in lower_content:
            errors.append(f"Design should explicitly cover {phrase}-level details.")
    return errors


def review_check(target: Path, root: Path | None = None) -> None:
    kind, path = _resolve_target(target, root=root)
    if kind == "idea":
        errors = _check_idea(path)
    else:
        errors = _check_design(path)

    if errors:
        print(f"{kind.title()} review check failed: {path}")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    print(f"{kind.title()} review check passed: {path}")
