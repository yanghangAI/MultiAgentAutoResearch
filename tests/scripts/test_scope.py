from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib import scope  # noqa: E402
from scripts.tools.setup_design import setup_design  # noqa: E402


MINIMAL_CONFIG = (
    '{"results": {"metric_fields": ["val_loss"], "primary_metric": "val_loss"},'
    ' "setup_design": {"source_globs": ["*.py"], "destination_subdir": "code",'
    ' "output_patch": {"enabled": false}},'
    ' "integrity": {"immutable_paths": ["infra/**"]}}'
)


def _init_project(root: Path) -> None:
    (root / ".automation.json").write_text(MINIMAL_CONFIG, encoding="utf-8")
    baseline = root / "baseline"
    baseline.mkdir(parents=True)
    (baseline / "train.py").write_text("print('train')\n", encoding="utf-8")


def _write_summary(design_dir: Path, files_changed: list[str]) -> None:
    if files_changed:
        bullets = "\n".join(f"- `{p}`" for p in files_changed)
    else:
        bullets = ""
    content = (
        "# Implementation Summary\n\n"
        "**Files changed:**\n"
        f"{bullets}\n\n"
        "**Changes:** misc.\n"
    )
    (design_dir / "implementation_summary.md").write_text(content, encoding="utf-8")


def test_setup_design_writes_parent(tmp_path: Path) -> None:
    _init_project(tmp_path)
    dst = tmp_path / "runs" / "idea001" / "design001"
    setup_design(src=tmp_path / "baseline", dst=dst, root=tmp_path)
    parent_file = dst / scope.PARENT_FILENAME
    assert parent_file.exists()
    assert parent_file.read_text().strip() == str((tmp_path / "baseline").resolve())


def test_check_scope_passes_on_clean_baseline_copy(tmp_path: Path) -> None:
    _init_project(tmp_path)
    dst = tmp_path / "runs" / "idea001" / "design001"
    setup_design(src=tmp_path / "baseline", dst=dst, root=tmp_path)
    _write_summary(dst, [])

    report = scope.check_scope(dst, root=tmp_path)
    assert report.passed, report.render()
    assert report.undeclared_changes == []
    assert report.immutable_violations == []


def test_check_scope_flags_undeclared_change(tmp_path: Path) -> None:
    _init_project(tmp_path)
    dst = tmp_path / "runs" / "idea001" / "design001"
    setup_design(src=tmp_path / "baseline", dst=dst, root=tmp_path)
    (dst / "code" / "train.py").write_text("print('modified')\n", encoding="utf-8")
    _write_summary(dst, [])  # no files declared

    report = scope.check_scope(dst, root=tmp_path)
    assert not report.passed
    assert "train.py" in report.undeclared_changes


def test_check_scope_accepts_declared_change(tmp_path: Path) -> None:
    _init_project(tmp_path)
    dst = tmp_path / "runs" / "idea001" / "design001"
    setup_design(src=tmp_path / "baseline", dst=dst, root=tmp_path)
    (dst / "code" / "train.py").write_text("print('modified')\n", encoding="utf-8")
    _write_summary(dst, ["train.py"])

    report = scope.check_scope(dst, root=tmp_path)
    assert report.passed, report.render()


def test_check_scope_detects_immutable_violation(tmp_path: Path) -> None:
    _init_project(tmp_path)
    dst = tmp_path / "runs" / "idea001" / "design001"
    setup_design(src=tmp_path / "baseline", dst=dst, root=tmp_path)
    # Design creates a file under the immutable path `infra/**`. Baseline has
    # no such file — declaration does NOT bypass immutability.
    infra_dir = dst / "code" / "infra"
    infra_dir.mkdir(parents=True)
    (infra_dir / "metrics.py").write_text("def m(): return 999\n", encoding="utf-8")
    _write_summary(dst, ["infra/metrics.py"])

    report = scope.check_scope(dst, root=tmp_path)
    assert not report.passed
    assert "infra/metrics.py" in report.immutable_violations


def test_check_scope_writes_pass_marker_and_cleans_fail(tmp_path: Path) -> None:
    _init_project(tmp_path)
    dst = tmp_path / "runs" / "idea001" / "design001"
    setup_design(src=tmp_path / "baseline", dst=dst, root=tmp_path)
    (dst / scope.SCOPE_FAIL).write_text("stale\n", encoding="utf-8")
    _write_summary(dst, [])

    rc = scope.run_check_scope(dst, root=tmp_path)
    assert rc == 0
    assert (dst / scope.SCOPE_PASS).exists()
    assert not (dst / scope.SCOPE_FAIL).exists()


def test_setup_design_refuses_parent_without_scope_pass(tmp_path: Path) -> None:
    _init_project(tmp_path)
    # Pretend design001 has already been bootstrapped and implemented.
    design1 = tmp_path / "runs" / "idea001" / "design001"
    setup_design(src=tmp_path / "baseline", dst=design1, root=tmp_path)
    # Put the idea overview CSV in place so _validate_source_status can succeed.
    csv_path = tmp_path / "runs" / "idea001" / "design_overview.csv"
    csv_path.write_text(
        "Design_ID,Status\ndesign001,Implemented\n", encoding="utf-8"
    )
    design2 = tmp_path / "runs" / "idea001" / "design002"

    import pytest
    with pytest.raises(SystemExit) as exc:
        setup_design(src=design1, dst=design2, root=tmp_path)
    assert "scope_check" in str(exc.value)


def test_setup_design_accepts_parent_with_scope_pass(tmp_path: Path) -> None:
    _init_project(tmp_path)
    design1 = tmp_path / "runs" / "idea001" / "design001"
    setup_design(src=tmp_path / "baseline", dst=design1, root=tmp_path)
    _write_summary(design1, [])
    scope.run_check_scope(design1, root=tmp_path)
    csv_path = tmp_path / "runs" / "idea001" / "design_overview.csv"
    csv_path.write_text(
        "Design_ID,Status\ndesign001,Implemented\n", encoding="utf-8"
    )
    design2 = tmp_path / "runs" / "idea001" / "design002"
    setup_design(src=design1, dst=design2, root=tmp_path)
    assert (design2 / scope.PARENT_FILENAME).exists()


def test_lineage_walks_chain(tmp_path: Path) -> None:
    _init_project(tmp_path)
    design1 = tmp_path / "runs" / "idea001" / "design001"
    setup_design(src=tmp_path / "baseline", dst=design1, root=tmp_path)
    _write_summary(design1, [])
    scope.run_check_scope(design1, root=tmp_path)
    csv_path = tmp_path / "runs" / "idea001" / "design_overview.csv"
    csv_path.write_text(
        "Design_ID,Status\ndesign001,Implemented\n", encoding="utf-8"
    )
    design2 = tmp_path / "runs" / "idea001" / "design002"
    setup_design(src=design1, dst=design2, root=tmp_path)

    chain = scope.walk_lineage(design2, root=tmp_path)
    assert chain[0] == design2.resolve()
    assert chain[1] == design1.resolve()
    assert chain[-1] == (tmp_path / "baseline").resolve()
