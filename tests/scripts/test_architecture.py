from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib import layout
from scripts.lib.dashboard import build_dashboard
from scripts.lib.results import summarize_results
from scripts.lib.status import derive_design_status, derive_idea_status, get_expected_designs

CLI_PATH = REPO_ROOT / "scripts" / "cli.py"


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args, "--root", str(root)],
        text=True,
        capture_output=True,
        cwd=root,
    )


def init_status_fixture(root: Path) -> None:
    write_csv(
        root / "runs" / "idea_overview.csv",
        ["Idea_ID", "Idea_Name", "Status"],
        [["idea001", "Idea One", "Not Designed"]],
    )
    write_csv(
        root / "runs" / "idea001" / "design_overview.csv",
        ["Design_ID", "Design_Description", "Status"],
        [["design001", "first", "Designed"], ["design002", "second", "Designed"]],
    )
    (root / "runs" / "idea001" / "idea.md").write_text("**Expected Designs:** 2\n", encoding="utf-8")
    (root / "runs" / "idea001" / "design001").mkdir(parents=True, exist_ok=True)
    (root / "runs" / "idea001" / "design002").mkdir(parents=True, exist_ok=True)


def test_layout_resolve_train_script_prefers_code_dir(tmp_path: Path) -> None:
    design = tmp_path / "runs" / "idea001" / "design001"
    (design / "code").mkdir(parents=True)
    (design / "code" / "train.py").write_text("print('code')\n", encoding="utf-8")
    (design / "train.py").write_text("print('flat')\n", encoding="utf-8")
    assert layout.resolve_train_script(design) == design / "code" / "train.py"


def test_layout_resolve_train_script_falls_back_to_flat_layout(tmp_path: Path) -> None:
    design = tmp_path / "runs" / "idea001" / "design001"
    design.mkdir(parents=True)
    (design / "train.py").write_text("print('flat')\n", encoding="utf-8")
    assert layout.resolve_train_script(design) == design / "train.py"


def test_summarize_results_ignores_test_output_and_bad_rows(tmp_path: Path) -> None:
    metrics_dir = tmp_path / "runs" / "idea001" / "design001"
    metrics_dir.mkdir(parents=True)
    write_csv(
        metrics_dir / "metrics.csv",
        ["epoch", "train_mpjpe_weighted", "val_mpjpe_weighted"],
        [["1", "10.0", "12.0"], ["20", "8.0", "9.0"]],
    )
    ignored_dir = metrics_dir / "test_output"
    ignored_dir.mkdir()
    write_csv(
        ignored_dir / "metrics.csv",
        ["epoch", "train_mpjpe_weighted", "val_mpjpe_weighted"],
        [["99", "1.0", "1.0"]],
    )
    bad_dir = tmp_path / "runs" / "idea002" / "design001"
    bad_dir.mkdir(parents=True)
    write_csv(bad_dir / "metrics.csv", ["epoch", "something_else"], [["2", "x"]])

    records = summarize_results(root=tmp_path)

    assert len(records) == 1
    output = (tmp_path / "results.csv").read_text(encoding="utf-8")
    assert "idea001,design001,20,8.0,9.0" in output
    assert "99,1.0,1.0" not in output


def test_status_derivation_from_reviews_and_expected_designs(tmp_path: Path) -> None:
    init_status_fixture(tmp_path)
    (tmp_path / "runs" / "idea001" / "design001" / "code_review.md").write_text(
        "APPROVED\n",
        encoding="utf-8",
    )
    (tmp_path / "runs" / "idea001" / "design002" / "review.md").write_text(
        "APPROVED\n",
        encoding="utf-8",
    )

    assert get_expected_designs("idea001", root=tmp_path) == 2
    assert derive_design_status("idea001", "design001", root=tmp_path) == "Implemented"
    assert derive_design_status("idea001", "design002", root=tmp_path) == "Not Implemented"
    assert derive_idea_status("idea001", root=tmp_path) == "Designed"


def test_status_derivation_marks_submitted_and_training(tmp_path: Path) -> None:
    init_status_fixture(tmp_path)
    design = tmp_path / "runs" / "idea001" / "design001"
    (design / "code_review.md").write_text("APPROVED\n", encoding="utf-8")
    (design / "slurm_123.out").write_text("submitted\n", encoding="utf-8")
    write_csv(
        tmp_path / "results.csv",
        ["idea_id", "design_id", "epoch", "train_mpjpe_weighted", "val_mpjpe_weighted"],
        [["idea001", "design002", "3", "10.0", "11.0"]],
    )

    assert derive_design_status("idea001", "design001", root=tmp_path) == "Submitted"
    assert derive_design_status("idea001", "design002", root=tmp_path) == "Training"


def test_sync_status_cli_updates_csvs(tmp_path: Path) -> None:
    init_status_fixture(tmp_path)
    write_csv(
        tmp_path / "runs" / "idea001" / "design001" / "metrics.csv",
        ["epoch", "train_mpjpe_weighted", "val_mpjpe_weighted"],
        [["20", "8.0", "9.0"]],
    )
    (tmp_path / "runs" / "idea001" / "design002" / "code_review.md").write_text(
        "APPROVED\n",
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "sync-status")

    assert result.returncode == 0, result.stderr
    design_csv = (tmp_path / "runs" / "idea001" / "design_overview.csv").read_text(encoding="utf-8")
    idea_csv = (tmp_path / "runs" / "idea_overview.csv").read_text(encoding="utf-8")
    assert "design001,first,Done" in design_csv
    assert "design002,second,Implemented" in design_csv
    assert "idea001,Idea One,Implemented" in idea_csv


def test_submit_implemented_dry_run_uses_canonical_train_path(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "runs" / "idea001" / "design_overview.csv",
        ["Design_ID", "Design_Description", "Status"],
        [["design001", "first", "Implemented"]],
    )
    design = tmp_path / "runs" / "idea001" / "design001" / "code"
    design.mkdir(parents=True)
    (design / "train.py").write_text("print('train')\n", encoding="utf-8")

    result = run_cli(tmp_path, "submit-implemented", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "idea001-design001" in result.stdout
    assert "design001/code/train.py" in result.stdout


def test_submit_test_dry_run_shows_sbatch_command(tmp_path: Path) -> None:
    target = tmp_path / "runs" / "idea001" / "design001"
    (target / "code").mkdir(parents=True)

    result = run_cli(tmp_path, "submit-test", str(target), "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "DRY RUN: would submit test job" in result.stdout
    assert "slurm_test.sh" in result.stdout
    assert str(target / "test_output" / "slurm_test_%j.out") in result.stdout


def test_build_dashboard_renders_expected_content(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "runs" / "idea_overview.csv",
        ["Idea_ID", "Idea_Name", "Status"],
        [["idea001", "Idea One", "Implemented"]],
    )
    write_csv(
        tmp_path / "results.csv",
        ["idea_id", "design_id", "epoch", "train_mpjpe_weighted", "val_mpjpe_weighted"],
        [["idea001", "design001", "20", "8.0", "9.0"]],
    )
    (tmp_path / "runs" / "idea001").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs" / "idea001" / "idea.md").write_text("Example idea body\n", encoding="utf-8")

    build_dashboard(root=tmp_path)

    html = (tmp_path / "website" / "index.html").read_text(encoding="utf-8")
    assert "AutoSapiens Dashboard" in html
    assert "idea001" in html
    assert "9.00" in html


def test_deploy_dashboard_refuses_dirty_tree(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    (tmp_path / "website").mkdir()
    (tmp_path / "website" / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("root\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "gh-pages"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "dirty.txt").write_text("unsafe\n", encoding="utf-8")

    result = run_cli(tmp_path, "deploy-dashboard")

    assert result.returncode != 0
    assert "dirty git tree" in result.stderr or "dirty git tree" in result.stdout
