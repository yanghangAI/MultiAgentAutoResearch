from __future__ import annotations

import re
from pathlib import Path

from scripts.lib import claims, layout, scope, store


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
    idea_id = path.parent.name
    if not re.fullmatch(r"idea\d{3}", idea_id):
        errors.append(f"Idea folder name '{idea_id}' must match idea### (e.g. idea001).")
    if not _parse_bold_field(content, "Idea Name"):
        errors.append("Missing required field `**Idea Name:**`.")
    if not _parse_bold_field(content, "Approach"):
        errors.append("Missing required field `**Approach:**` (one sentence describing the core mechanism).")
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
    design_id = path.parent.name
    if not re.fullmatch(r"design\d{3}", design_id):
        errors.append(f"Design folder name '{design_id}' must match design### (e.g. design001).")
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


def _check_implementation(design_dir: Path) -> list[str]:
    errors: list[str] = []
    summary_path = design_dir / "implementation_summary.md"
    if not summary_path.exists():
        errors.append(
            "Missing `implementation_summary.md`. Builder must write this file listing "
            "every file changed and what changed."
        )
        return errors
    content = store.read_text(summary_path).strip()
    if not content:
        errors.append("`implementation_summary.md` is empty.")
        return errors
    if not re.search(r"\*\*Files changed:\*\*", content):
        errors.append(
            "`implementation_summary.md` must include a `**Files changed:**` section "
            "listing every modified file."
        )
    if not re.search(r"\*\*Changes:\*\*", content):
        errors.append(
            "`implementation_summary.md` must include a `**Changes:**` section "
            "describing what was changed in each file."
        )
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


def review_check_implementation(design_dir: Path, root: Path | None = None) -> None:
    root_path = layout.repo_root(root)
    resolved = design_dir if design_dir.is_absolute() else (root_path / design_dir)
    resolved = resolved.resolve()
    errors = _check_implementation(resolved)
    if errors:
        print(f"Implementation review check failed: {resolved}")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(f"Structural check passed: {resolved}")

    # Run scope and claims checks; collect failures before exiting so the
    # reviewer sees everything at once.
    scope_report = scope.check_scope(resolved, root=root_path)
    print("--- check-scope ---")
    print(scope_report.render(), end="")
    # Persist the scope marker (mirror of `scripts/cli.py check-scope`).
    (resolved / scope.SCOPE_PASS).unlink(missing_ok=True)
    (resolved / scope.SCOPE_FAIL).unlink(missing_ok=True)
    (resolved / (scope.SCOPE_PASS if scope_report.passed else scope.SCOPE_FAIL)).write_text(
        scope_report.render(), encoding="utf-8"
    )
    if not scope_report.passed:
        scope.record_scope_failure(resolved, scope_report, root=root_path)

    claims_report = claims.verify_claims(resolved, root=root_path)
    print("--- verify-claims ---")
    print(claims_report.render(), end="")
    if not claims_report.passed:
        claims.record_claims_failure(resolved, claims_report, root=root_path)

    if not scope_report.passed or not claims_report.passed:
        raise SystemExit(1)
    print(f"Implementation review check passed: {resolved}")
