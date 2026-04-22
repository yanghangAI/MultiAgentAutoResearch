from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib import claims, memory, scope  # noqa: E402
from scripts.tools.setup_design import setup_design  # noqa: E402


MINIMAL_CONFIG = (
    '{"results": {"metric_fields": ["val_loss"], "primary_metric": "val_loss"},'
    ' "setup_design": {"source_globs": ["*.py"], "destination_subdir": "code",'
    ' "output_patch": {"enabled": false}},'
    ' "integrity": {"immutable_paths": ["infra/**"]}}'
)


def _init(root: Path) -> None:
    (root / ".automation.json").write_text(MINIMAL_CONFIG, encoding="utf-8")
    baseline = root / "baseline"
    baseline.mkdir()
    (baseline / "train.py").write_text("x = 1\n", encoding="utf-8")


def _summary(design: Path, bullets: list[str], extra: str = "") -> None:
    body = "\n".join(f"- `{b}`" for b in bullets) if bullets else ""
    (design / "implementation_summary.md").write_text(
        f"**Files changed:**\n{body}\n\n**Changes:** x.\n{extra}",
        encoding="utf-8",
    )


def test_scope_failure_appends_to_builder_memory(tmp_path: Path) -> None:
    _init(tmp_path)
    design = tmp_path / "runs" / "idea001" / "design001"
    setup_design(src=tmp_path / "baseline", dst=design, root=tmp_path)
    # Introduce an undeclared change
    (design / "code" / "train.py").write_text("x = 2\n", encoding="utf-8")
    _summary(design, [])  # declare nothing

    mem_path = memory.memory_path("Builder", root=tmp_path)
    before = mem_path.exists()
    rc = scope.run_check_scope(design, root=tmp_path)
    assert rc == 1
    assert mem_path.exists()
    content = mem_path.read_text(encoding="utf-8")
    assert "scope_check failed" in content
    assert "undeclared changes" in content
    if before:
        # Should have appended, not overwritten
        assert content.count("scope_check failed") >= 1


def test_scope_success_does_not_append(tmp_path: Path) -> None:
    _init(tmp_path)
    design = tmp_path / "runs" / "idea001" / "design001"
    setup_design(src=tmp_path / "baseline", dst=design, root=tmp_path)
    _summary(design, [])  # no changes, nothing declared — clean
    mem_path = memory.memory_path("Builder", root=tmp_path)

    rc = scope.run_check_scope(design, root=tmp_path)
    assert rc == 0
    assert not mem_path.exists()


def test_claims_failure_appends_to_builder_memory(tmp_path: Path) -> None:
    _init(tmp_path)
    design = tmp_path / "runs" / "idea001" / "design001"
    (design / "code").mkdir(parents=True)
    (design / "code" / "train.py").write_text("unrelated = True\n", encoding="utf-8")
    (design / "implementation_summary.md").write_text(
        "**Files changed:**\n- `code/train.py`\n\n"
        "In `code/train.py`:\n\n"
        "```python\nmissing_snippet = 42\n```\n",
        encoding="utf-8",
    )

    mem_path = memory.memory_path("Builder", root=tmp_path)
    rc = claims.run_verify_claims(design, root=tmp_path)
    assert rc == 1
    assert mem_path.exists()
    content = mem_path.read_text(encoding="utf-8")
    assert "verify_claims failed" in content
    assert "claim not in" in content


def test_claims_success_does_not_append(tmp_path: Path) -> None:
    _init(tmp_path)
    design = tmp_path / "runs" / "idea001" / "design001"
    (design / "code").mkdir(parents=True)
    (design / "code" / "train.py").write_text("x = 42\n", encoding="utf-8")
    (design / "implementation_summary.md").write_text(
        "In `code/train.py`:\n\n"
        "```python\nx = 42\n```\n",
        encoding="utf-8",
    )
    mem_path = memory.memory_path("Builder", root=tmp_path)
    rc = claims.run_verify_claims(design, root=tmp_path)
    assert rc == 0
    assert not mem_path.exists()


def test_mistake_entry_is_well_formed(tmp_path: Path) -> None:
    entry = memory.MistakeEntry(
        title="t", what_i_did="w", why_wrong="y", how_to_avoid="h", source="s"
    )
    memory.append_mistake("Builder", entry, root=tmp_path)
    path = memory.memory_path("Builder", root=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "## " in text  # dated header
    assert "**What I did:** w" in text
    assert "**Why it was wrong:** y" in text
    assert "**How to avoid:** h" in text
    assert "**Source:** s" in text
