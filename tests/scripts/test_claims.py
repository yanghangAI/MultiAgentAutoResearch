from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib import claims  # noqa: E402


MINIMAL_CONFIG = (
    '{"results": {"metric_fields": ["val_loss"], "primary_metric": "val_loss"},'
    ' "setup_design": {"source_globs": ["*.py"], "destination_subdir": "code",'
    ' "output_patch": {"enabled": false}}}'
)


def _scaffold(tmp_path: Path, summary: str, files: dict[str, str]) -> Path:
    (tmp_path / ".automation.json").write_text(MINIMAL_CONFIG, encoding="utf-8")
    design = tmp_path / "runs" / "idea001" / "design001"
    code = design / "code"
    code.mkdir(parents=True)
    for rel, content in files.items():
        path = code / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (design / "implementation_summary.md").write_text(summary, encoding="utf-8")
    return design


def test_no_fenced_blocks_passes(tmp_path: Path) -> None:
    design = _scaffold(
        tmp_path,
        "**Files changed:**\n- `code/train.py`\n\n**Changes:** added L2.\n",
        {"train.py": "print('hi')\n"},
    )
    report = claims.verify_claims(design, root=tmp_path)
    assert report.passed, report.render()
    assert report.checked == 0


def test_attributed_snippet_found(tmp_path: Path) -> None:
    summary = (
        "**Files changed:**\n- `code/train.py`\n\n"
        "In `code/train.py`, added:\n\n"
        "```python\nloss = ce + 0.01 * l2\n```\n"
    )
    design = _scaffold(
        tmp_path,
        summary,
        {"train.py": "x=1\nloss = ce + 0.01 * l2\ny=2\n"},
    )
    report = claims.verify_claims(design, root=tmp_path)
    assert report.passed, report.render()
    assert report.checked == 1
    assert report.missing == []


def test_attributed_snippet_not_found_fails(tmp_path: Path) -> None:
    summary = (
        "In `code/train.py`, added:\n\n"
        "```python\nloss = ce + 0.01 * l2\n```\n"
    )
    design = _scaffold(
        tmp_path,
        summary,
        {"train.py": "x=1\n"},  # snippet NOT present
    )
    report = claims.verify_claims(design, root=tmp_path)
    assert not report.passed
    assert len(report.missing) == 1
    assert report.missing[0][0] == "code/train.py"


def test_claimed_file_missing_fails(tmp_path: Path) -> None:
    summary = (
        "In `code/nonexistent.py`, added:\n\n"
        "```python\nx = 1\n```\n"
    )
    design = _scaffold(tmp_path, summary, {"train.py": "y = 2\n"})
    report = claims.verify_claims(design, root=tmp_path)
    assert not report.passed
    assert "file not found" in report.missing[0][1]


def test_unattributed_snippet_warns_does_not_fail(tmp_path: Path) -> None:
    # Block has no preceding file token at all.
    summary = (
        "Some prose with no file reference.\n\n"
        "```python\nx = 1\n```\n"
    )
    design = _scaffold(tmp_path, summary, {"train.py": "x = 1\n"})
    report = claims.verify_claims(design, root=tmp_path)
    assert report.passed, report.render()
    assert len(report.unattributed) == 1
    assert report.checked == 0


def test_whitespace_tolerance(tmp_path: Path) -> None:
    summary = (
        "In `code/train.py`:\n\n"
        "```python\nloss  =  ce  +  0.01 * l2\n```\n"
    )
    design = _scaffold(
        tmp_path,
        summary,
        {"train.py": "loss = ce + 0.01 * l2\n"},  # different spacing
    )
    report = claims.verify_claims(design, root=tmp_path)
    assert report.passed, report.render()


def test_attribution_from_bullet_above_block(tmp_path: Path) -> None:
    # A blank line between the bullet and the fence does not break attribution —
    # the walker skips leading blanks and picks up the bullet.
    summary = (
        "**Changes:**\n"
        "- `code/train.py`\n"
        "\n"
        "```python\nloss = x\n```\n"
    )
    design = _scaffold(tmp_path, summary, {"train.py": "loss = x\n"})
    report = claims.verify_claims(design, root=tmp_path)
    assert report.passed, report.render()
    assert report.checked == 1
    assert report.unattributed == []


def test_attribution_from_prose_line_directly_above(tmp_path: Path) -> None:
    summary = (
        "In `code/train.py`, the change:\n"
        "```python\nloss = x\n```\n"
    )
    design = _scaffold(tmp_path, summary, {"train.py": "loss = x\n"})
    report = claims.verify_claims(design, root=tmp_path)
    assert report.passed, report.render()
    assert report.checked == 1
