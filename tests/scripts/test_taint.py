from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib import scope  # noqa: E402
from scripts.lib.context import ProjectContext  # noqa: E402
from scripts.lib.models import Status  # noqa: E402
from scripts.lib.status import derive_design_status  # noqa: E402
from scripts.lib.results import summarize_results  # noqa: E402


MINIMAL_CONFIG = (
    '{"results": {"metric_fields": ["val_loss"], "primary_metric": "val_loss",'
    ' "metrics_glob": "**/metrics.csv", "exclude_path_parts": ["test_output"]},'
    ' "status": {"progress_field": "epoch", "done_value": 2, "approved_token": "APPROVED"},'
    ' "setup_design": {"source_globs": ["*.py"], "destination_subdir": "code",'
    ' "output_patch": {"enabled": false}}}'
)


def _init(root: Path) -> None:
    (root / ".automation.json").write_text(MINIMAL_CONFIG, encoding="utf-8")
    (root / "baseline").mkdir()


def _mk_design(root: Path, idea: str, design: str, parent: Path, tainted: bool = False) -> Path:
    design_dir = root / "runs" / idea / design
    (design_dir / "code").mkdir(parents=True)
    (design_dir / ".parent").write_text(str(parent.resolve()) + "\n", encoding="utf-8")
    if tainted:
        (design_dir / scope.SCOPE_FAIL).write_text("bad\n", encoding="utf-8")
    else:
        (design_dir / scope.SCOPE_PASS).write_text("ok\n", encoding="utf-8")
    return design_dir


def test_self_tainted(tmp_path: Path) -> None:
    _init(tmp_path)
    d = _mk_design(tmp_path, "idea001", "design001", tmp_path / "baseline", tainted=True)
    assert scope.is_tainted(d, root=tmp_path)


def test_clean_chain_not_tainted(tmp_path: Path) -> None:
    _init(tmp_path)
    d1 = _mk_design(tmp_path, "idea001", "design001", tmp_path / "baseline")
    d2 = _mk_design(tmp_path, "idea001", "design002", d1)
    assert not scope.is_tainted(d2, root=tmp_path)


def test_inherited_taint(tmp_path: Path) -> None:
    _init(tmp_path)
    d1 = _mk_design(tmp_path, "idea001", "design001", tmp_path / "baseline", tainted=True)
    d2 = _mk_design(tmp_path, "idea001", "design002", d1)
    d3 = _mk_design(tmp_path, "idea002", "design001", d2)  # cross-idea child
    assert scope.is_tainted(d3, root=tmp_path)


def test_derive_design_status_returns_tainted(tmp_path: Path) -> None:
    _init(tmp_path)
    # Scaffold design with an approved code review that would normally be IMPLEMENTED,
    # plus a scope_check.fail marker. Expect TAINTED to override.
    d = _mk_design(tmp_path, "idea001", "design001", tmp_path / "baseline", tainted=True)
    (d / "code_review.md").write_text("APPROVED\n", encoding="utf-8")
    ctx = ProjectContext.create(tmp_path)
    assert derive_design_status("idea001", "design001", ctx) == Status.TAINTED


def test_summarize_results_skips_tainted(tmp_path: Path) -> None:
    _init(tmp_path)
    d_ok = _mk_design(tmp_path, "idea001", "design001", tmp_path / "baseline")
    d_bad = _mk_design(tmp_path, "idea001", "design002", tmp_path / "baseline", tainted=True)
    for design in (d_ok, d_bad):
        (design / "metrics.csv").write_text("epoch,val_loss\n2,0.1\n", encoding="utf-8")
    ctx = ProjectContext.create(tmp_path)
    records = summarize_results(ctx)
    ids = {(r.idea_id, r.design_id) for r in records}
    assert ("idea001", "design001") in ids
    assert ("idea001", "design002") not in ids
