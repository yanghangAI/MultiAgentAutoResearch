from __future__ import annotations

import sys
import unittest.mock as mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib import store


def test_write_dict_rows_produces_correct_csv(tmp_path: Path) -> None:
    target = tmp_path / "data.csv"
    store.write_dict_rows(
        target,
        ["Name", "Value"],
        [{"Name": "alpha", "Value": "1"}, {"Name": "beta", "Value": "2"}],
    )
    content = target.read_text(encoding="utf-8")
    assert "Name,Value" in content
    assert "alpha,1" in content
    assert "beta,2" in content


def test_write_dict_rows_does_not_corrupt_target_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "data.csv"
    target.write_text("Name,Value\noriginal,0\n", encoding="utf-8")

    with mock.patch("os.rename", side_effect=OSError("simulated crash")):
        try:
            store.write_dict_rows(
                target,
                ["Name", "Value"],
                [{"Name": "new", "Value": "1"}],
            )
        except OSError:
            pass

    content = target.read_text(encoding="utf-8")
    assert "original,0" in content
    assert "new,1" not in content


def test_write_csv_rows_produces_correct_csv(tmp_path: Path) -> None:
    target = tmp_path / "data.csv"
    store.write_csv_rows(target, [["Name", "Value"], ["alpha", "1"], ["beta", "2"]])
    content = target.read_text(encoding="utf-8")
    assert "Name,Value" in content
    assert "alpha,1" in content
    assert "beta,2" in content


def test_write_csv_rows_does_not_corrupt_target_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "data.csv"
    target.write_text("Name,Value\noriginal,0\n", encoding="utf-8")

    with mock.patch("os.rename", side_effect=OSError("simulated crash")):
        try:
            store.write_csv_rows(target, [["Name", "Value"], ["new", "1"]])
        except OSError:
            pass

    content = target.read_text(encoding="utf-8")
    assert "original,0" in content
    assert "new,1" not in content
