from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.context import ProjectContext


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def test_context_resolves_root(tmp_path: Path) -> None:
    ctx = ProjectContext.create(tmp_path)
    assert ctx.root == tmp_path.resolve()


def test_context_loads_cfg_lazily(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        '{"results": {"metric_fields": ["val_loss"], "primary_metric": "val_loss"}}',
        encoding="utf-8",
    )
    ctx = ProjectContext.create(tmp_path)
    assert "cfg" not in ctx.__dict__  # not loaded yet
    assert ctx.cfg.results.primary_metric == "val_loss"
    assert "cfg" in ctx.__dict__  # now cached


def test_context_loads_results_index_lazily(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "results.csv",
        ["idea_id", "design_id", "epoch", "val_loss"],
        [["idea001", "design001", "20", "0.5"]],
    )
    ctx = ProjectContext.create(tmp_path)
    assert "results_index" not in ctx.__dict__
    assert ("idea001", "design001") in ctx.results_index
    assert "results_index" in ctx.__dict__


def test_context_is_frozen(tmp_path: Path) -> None:
    ctx = ProjectContext.create(tmp_path)
    import pytest
    with pytest.raises(AttributeError):
        ctx.root = tmp_path / "other"
