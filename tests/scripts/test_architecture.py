from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lib import layout
import time

from scripts.lib.context import ProjectContext
from scripts.lib.dashboard import build_dashboard
from scripts.lib.project_config import ProjectConfig, StatusConfig
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
    (root / "runs" / "idea001" / "idea.md").write_text(
        "**Idea Name:** Idea One\n**Expected Designs:** 2\n",
        encoding="utf-8",
    )
    d1 = root / "runs" / "idea001" / "design001"
    d1.mkdir(parents=True, exist_ok=True)
    (d1 / "design.md").write_text("**Design Description:** first\n", encoding="utf-8")
    (d1 / "design_review.md").write_text("APPROVED\n", encoding="utf-8")
    d2 = root / "runs" / "idea001" / "design002"
    d2.mkdir(parents=True, exist_ok=True)
    (d2 / "design.md").write_text("**Design Description:** second\n", encoding="utf-8")
    (d2 / "design_review.md").write_text("APPROVED\n", encoding="utf-8")


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

    records = summarize_results(ProjectContext.create(tmp_path))

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
    (tmp_path / "runs" / "idea001" / "design002" / "design_review.md").write_text(
        "APPROVED\n",
        encoding="utf-8",
    )

    assert get_expected_designs("idea001", root=tmp_path) == 2
    assert derive_design_status("idea001", "design001", ProjectContext.create(tmp_path)) == "Implemented"
    assert derive_design_status("idea001", "design002", ProjectContext.create(tmp_path)) == "Not Implemented"
    assert derive_idea_status("idea001", root=tmp_path) == "Designed"


def test_status_derivation_marks_submitted_and_training(tmp_path: Path) -> None:
    init_status_fixture(tmp_path)
    design = tmp_path / "runs" / "idea001" / "design001"
    (design / "code_review.md").write_text("APPROVED\n", encoding="utf-8")
    (design / "job_submitted.txt").write_text("Submitted: idea001-design001\n", encoding="utf-8")
    write_csv(
        tmp_path / "results.csv",
        ["idea_id", "design_id", "epoch", "train_mpjpe_weighted", "val_mpjpe_weighted"],
        [["idea001", "design002", "3", "10.0", "11.0"]],
    )

    assert derive_design_status("idea001", "design001", ProjectContext.create(tmp_path)) == "Submitted"
    assert derive_design_status("idea001", "design002", ProjectContext.create(tmp_path)) == "Training"


def test_status_derivation_marks_submission_stale(tmp_path: Path) -> None:
    init_status_fixture(tmp_path)
    design = tmp_path / "runs" / "idea001" / "design001"
    (design / "code_review.md").write_text("APPROVED\n", encoding="utf-8")
    submitted_path = design / "job_submitted.txt"
    submitted_path.write_text("Submitted: idea001-design001\n", encoding="utf-8")
    # backdate mtime by 49 hours to simulate a stale submission
    past = time.time() - 49 * 3600
    import os
    os.utime(submitted_path, (past, past))
    cfg = ProjectConfig(status=StatusConfig(submission_timeout_hours=48.0))

    assert derive_design_status("idea001", "design001", ProjectContext.create(tmp_path, cfg=cfg)) == "Submission Stale"


def test_status_derivation_marks_training_failed(tmp_path: Path) -> None:
    init_status_fixture(tmp_path)
    design = tmp_path / "runs" / "idea001" / "design001"
    (design / "code_review.md").write_text("APPROVED\n", encoding="utf-8")
    (design / "job_submitted.txt").write_text("Submitted: idea001-design001\n", encoding="utf-8")
    (design / "training_failed.txt").write_text("OOM error\n", encoding="utf-8")

    assert derive_design_status("idea001", "design001", ProjectContext.create(tmp_path)) == "Training Failed"


def test_status_derivation_marks_implement_failed(tmp_path: Path) -> None:
    init_status_fixture(tmp_path)
    design = tmp_path / "runs" / "idea001" / "design001"
    (design / "implement_failed.md").write_text("Blocked after repeated failures\n", encoding="utf-8")

    assert derive_design_status("idea001", "design001", ProjectContext.create(tmp_path)) == "Implement Failed"


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


def test_sync_status_marks_implement_failed_in_csv(tmp_path: Path) -> None:
    init_status_fixture(tmp_path)
    (tmp_path / "runs" / "idea001" / "design001" / "implement_failed.md").write_text(
        "Blocked after repeated failures\n",
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "sync-status")

    assert result.returncode == 0, result.stderr
    design_csv = (tmp_path / "runs" / "idea001" / "design_overview.csv").read_text(encoding="utf-8")
    idea_csv = (tmp_path / "runs" / "idea_overview.csv").read_text(encoding="utf-8")
    assert "design001,first,Implement Failed" in design_csv
    assert "idea001,Idea One,Designed" in idea_csv


def test_add_idea_cli_registers_idea_and_creates_design_tracker(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "add-idea", "idea002", "Idea Two")

    assert result.returncode == 0, result.stderr
    idea_csv = (tmp_path / "runs" / "idea_overview.csv").read_text(encoding="utf-8")
    design_csv = (tmp_path / "runs" / "idea002" / "design_overview.csv").read_text(encoding="utf-8")
    assert "idea002,Idea Two,Not Designed" in idea_csv
    assert "Design_ID,Design_Description,Status" in design_csv


def test_sync_status_auto_registers_new_idea_folder(tmp_path: Path) -> None:
    idea_dir = tmp_path / "runs" / "idea002"
    idea_dir.mkdir(parents=True)
    (idea_dir / "idea.md").write_text(
        "**Idea Name:** Depth-Aware Augmentation\n**Expected Designs:** 1\n**Baseline Source:** baseline/\n",
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "sync-status")

    assert result.returncode == 0, result.stderr
    idea_csv = (tmp_path / "runs" / "idea_overview.csv").read_text(encoding="utf-8")
    design_csv = (tmp_path / "runs" / "idea002" / "design_overview.csv").read_text(encoding="utf-8")
    assert "idea002,Depth-Aware Augmentation,Not Designed" in idea_csv
    assert "Design_ID,Design_Description,Status" in design_csv


def test_add_design_cli_registers_design_and_creates_directory(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "runs" / "idea001" / "design_overview.csv",
        ["Design_ID", "Design_Description", "Status"],
        [],
    )

    result = run_cli(tmp_path, "add-design", "idea001", "design003", "Third Design")

    assert result.returncode == 0, result.stderr
    design_csv = (tmp_path / "runs" / "idea001" / "design_overview.csv").read_text(encoding="utf-8")
    assert "design003,Third Design,Not Implemented" in design_csv
    assert (tmp_path / "runs" / "idea001" / "design003").is_dir()


def test_add_design_cli_parses_description_from_design_md(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "runs" / "idea001" / "design_overview.csv",
        ["Design_ID", "Design_Description", "Status"],
        [],
    )
    design_dir = tmp_path / "runs" / "idea001" / "design004"
    design_dir.mkdir(parents=True)
    (design_dir / "design.md").write_text(
        "**Design Description:** Fourth Design\n",
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "add-design", "idea001", "design004")

    assert result.returncode == 0, result.stderr
    design_csv = (tmp_path / "runs" / "idea001" / "design_overview.csv").read_text(encoding="utf-8")
    assert "design004,Fourth Design,Not Implemented" in design_csv


def test_sync_status_auto_registers_new_design_folder(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "runs" / "idea001" / "design_overview.csv",
        ["Design_ID", "Design_Description", "Status"],
        [],
    )
    write_csv(
        tmp_path / "runs" / "idea_overview.csv",
        ["Idea_ID", "Idea_Name", "Status"],
        [["idea001", "Idea One", "Not Designed"]],
    )
    (tmp_path / "runs" / "idea001" / "idea.md").write_text(
        "**Idea Name:** Idea One\n**Expected Designs:** 1\n",
        encoding="utf-8",
    )
    design_dir = tmp_path / "runs" / "idea001" / "design003"
    design_dir.mkdir(parents=True)
    (design_dir / "design.md").write_text(
        "**Design Description:** Stronger Augmentation Sweep\n",
        encoding="utf-8",
    )
    (design_dir / "design_review.md").write_text("APPROVED\n", encoding="utf-8")

    result = run_cli(tmp_path, "sync-status")

    assert result.returncode == 0, result.stderr
    design_csv = (tmp_path / "runs" / "idea001" / "design_overview.csv").read_text(encoding="utf-8")
    idea_csv = (tmp_path / "runs" / "idea_overview.csv").read_text(encoding="utf-8")
    assert "design003,Stronger Augmentation Sweep,Not Implemented" in design_csv
    assert "idea001,Idea One,Designed" in idea_csv


def test_sync_status_skips_unapproved_new_design_folder(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "runs" / "idea001" / "design_overview.csv",
        ["Design_ID", "Design_Description", "Status"],
        [],
    )
    write_csv(
        tmp_path / "runs" / "idea_overview.csv",
        ["Idea_ID", "Idea_Name", "Status"],
        [["idea001", "Idea One", "Not Designed"]],
    )
    (tmp_path / "runs" / "idea001" / "idea.md").write_text(
        "**Idea Name:** Idea One\n**Expected Designs:** 1\n",
        encoding="utf-8",
    )
    design_dir = tmp_path / "runs" / "idea001" / "design004"
    design_dir.mkdir(parents=True)
    (design_dir / "design.md").write_text(
        "**Design Description:** Unapproved Sweep\n",
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "sync-status")

    assert result.returncode == 0, result.stderr
    design_csv = (tmp_path / "runs" / "idea001" / "design_overview.csv").read_text(encoding="utf-8")
    idea_csv = (tmp_path / "runs" / "idea_overview.csv").read_text(encoding="utf-8")
    assert "design004,Unapproved Sweep,Not Implemented" not in design_csv
    assert "idea001,Idea One,Not Designed" in idea_csv


def test_review_check_passes_for_valid_idea(tmp_path: Path) -> None:
    idea_dir = tmp_path / "runs" / "idea003"
    idea_dir.mkdir(parents=True)
    (idea_dir / "idea.md").write_text(
        "**Idea Name:** Temporal Fusion\n"
        "**Approach:** Apply cross-frame attention to fuse temporal context into pose estimation.\n"
        "**Expected Designs:** 2\n"
        "**Baseline Source:** baseline/\n",
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "review-check", "runs/idea003/idea.md")

    assert result.returncode == 0, result.stderr
    assert "Idea review check passed" in result.stdout


def test_review_check_fails_for_invalid_idea(tmp_path: Path) -> None:
    idea_dir = tmp_path / "runs" / "idea003"
    idea_dir.mkdir(parents=True)
    (idea_dir / "idea.md").write_text(
        "**Idea Name:** Temporal Fusion\n**Expected Designs:** nope\n",
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "review-check", "runs/idea003/idea.md")

    assert result.returncode != 0
    assert "Missing required field `**Approach:**`" in result.stdout
    assert "Missing required field `**Baseline Source:**`." in result.stdout
    assert "`**Expected Designs:**` must be a positive integer." in result.stdout


def test_review_check_passes_for_valid_design(tmp_path: Path) -> None:
    design_dir = tmp_path / "runs" / "idea003" / "design001"
    design_dir.mkdir(parents=True)
    (design_dir / "design.md").write_text(
        "**Design Description:** Short Sweep\n"
        "**Starting Point:** baseline/\n"
        "Files to change: code/train.py\n"
        "Algorithm changes: add temporal fusion block\n"
        "Config values: fusion_width=64\n",
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "review-check", "runs/idea003/design001")

    assert result.returncode == 0, result.stderr
    assert "Design review check passed" in result.stdout


def test_review_check_fails_for_invalid_design(tmp_path: Path) -> None:
    design_dir = tmp_path / "runs" / "idea003" / "design001"
    design_dir.mkdir(parents=True)
    (design_dir / "design.md").write_text(
        "**Design Description:** Short Sweep\n",
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "review-check", "runs/idea003/design001")

    assert result.returncode != 0
    assert "Missing required field `**Starting Point:**`." in result.stdout
    assert "Design should explicitly cover config-level details." in result.stdout


def test_review_check_implementation_passes_with_valid_summary(tmp_path: Path) -> None:
    # Scaffold a minimal valid design: baseline + code dir + .parent pointing to baseline.
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "train.py").write_text("x = 1\n", encoding="utf-8")

    design_dir = tmp_path / "runs" / "idea001" / "design001"
    code_dir = design_dir / "code"
    code_dir.mkdir(parents=True)
    (code_dir / "train.py").write_text("x = 2\n", encoding="utf-8")  # changed
    (design_dir / ".parent").write_text(str(baseline.resolve()) + "\n", encoding="utf-8")
    (design_dir / "implementation_summary.md").write_text(
        "**Files changed:** code/train.py\n\n"
        "**Changes:** Added layer-wise learning rate decay multiplier to optimizer setup.\n",
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "review-check-implementation", "runs/idea001/design001")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Implementation review check passed" in result.stdout


def test_review_check_implementation_fails_without_summary(tmp_path: Path) -> None:
    design_dir = tmp_path / "runs" / "idea001" / "design001"
    design_dir.mkdir(parents=True)

    result = run_cli(tmp_path, "review-check-implementation", "runs/idea001/design001")

    assert result.returncode != 0
    assert "Missing `implementation_summary.md`" in result.stdout


def test_review_check_implementation_fails_with_missing_sections(tmp_path: Path) -> None:
    design_dir = tmp_path / "runs" / "idea001" / "design001"
    design_dir.mkdir(parents=True)
    (design_dir / "implementation_summary.md").write_text(
        "I changed some stuff.\n",
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "review-check-implementation", "runs/idea001/design001")

    assert result.returncode != 0
    assert "**Files changed:**" in result.stdout
    assert "**Changes:**" in result.stdout


def test_config_loads_from_automation_json(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        '{"results": {"metric_fields": ["val_loss"], "primary_metric": "val_loss"}}',
        encoding="utf-8",
    )
    result = run_cli(tmp_path, "validate-config")
    assert result.returncode == 0, result.stderr


def test_config_errors_when_metric_fields_missing(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        '{"results": {"primary_metric": "val_loss"}}',
        encoding="utf-8",
    )
    result = run_cli(tmp_path, "validate-config")
    assert result.returncode != 0
    assert "metric_fields" in (result.stdout + result.stderr)


def test_config_errors_when_primary_metric_missing(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        '{"results": {"metric_fields": ["val_loss"]}}',
        encoding="utf-8",
    )
    result = run_cli(tmp_path, "validate-config")
    assert result.returncode != 0
    assert "primary_metric" in (result.stdout + result.stderr)


def test_validate_config_passes_with_valid_static_config(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        '{"results": {"metric_fields": ["val_loss"], "primary_metric": "val_loss"}, "status": {"done_value": 10}}',
        encoding="utf-8",
    )
    result = run_cli(tmp_path, "validate-config")
    assert result.returncode == 0, result.stderr
    assert "Config validation passed" in result.stdout


def test_validate_config_fails_when_primary_metric_not_in_fields(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        '{"results": {"metric_fields": ["train_loss"], "primary_metric": "val_loss"}}',
        encoding="utf-8",
    )
    result = run_cli(tmp_path, "validate-config")
    assert result.returncode != 0
    assert "primary_metric" in result.stdout


def test_validate_config_dynamic_check_finds_metrics(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        '{"results": {"metric_fields": ["val_loss"], "primary_metric": "val_loss", "metrics_glob": "**/metrics.csv"}}',
        encoding="utf-8",
    )
    search_dir = tmp_path / "test_output"
    search_dir.mkdir()
    write_csv(search_dir / "metrics.csv", ["epoch", "val_loss"], [["1", "0.5"]])

    result = run_cli(tmp_path, "validate-config", "--search-dir", str(search_dir))
    assert result.returncode == 0, result.stderr
    assert "Config validation passed" in result.stdout


def test_validate_config_dynamic_check_fails_on_missing_column(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        '{"results": {"metric_fields": ["val_loss", "val_acc"], "primary_metric": "val_loss", "metrics_glob": "**/metrics.csv"}}',
        encoding="utf-8",
    )
    search_dir = tmp_path / "test_output"
    search_dir.mkdir()
    write_csv(search_dir / "metrics.csv", ["epoch", "val_loss"], [["1", "0.5"]])

    result = run_cli(tmp_path, "validate-config", "--search-dir", str(search_dir))
    assert result.returncode != 0
    assert "val_acc" in result.stdout


def test_validate_config_dynamic_check_fails_when_glob_finds_nothing(tmp_path: Path) -> None:
    (tmp_path / ".automation.json").write_text(
        '{"results": {"metric_fields": ["val_loss"], "primary_metric": "val_loss", "metrics_glob": "**/metrics.csv"}}',
        encoding="utf-8",
    )
    search_dir = tmp_path / "test_output"
    search_dir.mkdir()

    result = run_cli(tmp_path, "validate-config", "--search-dir", str(search_dir))
    assert result.returncode != 0
    assert "found no files" in result.stdout


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


def test_submit_test_dry_run_shows_command(tmp_path: Path) -> None:
    target = tmp_path / "runs" / "idea001" / "design001"
    (target / "code").mkdir(parents=True)
    automation_yaml = tmp_path / ".automation.json"
    automation_yaml.write_text(
        '{"results": {"metric_fields": ["val_loss"], "primary_metric": "val_loss"}, "submit": {"submit_test_command_template": "bash {root}/scripts/local/submit_test.sh {target_dir} {test_output}"}}',
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "submit-test", str(target), "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "DRY RUN: would submit test job" in result.stdout
    assert "submit_test.sh" in result.stdout


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

    build_dashboard(ProjectContext.create(tmp_path))

    html = (tmp_path / "website" / "index.html").read_text(encoding="utf-8")
    assert "Multi-Agent Auto Research" in html
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


def test_deploy_dashboard_does_not_switch_current_branch(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    (tmp_path / "website").mkdir()
    (tmp_path / "website" / "index.html").write_text("<html>new dashboard</html>\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("root\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "gh-pages"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "index.html").write_text("<html>old dashboard</html>\n", encoding="utf-8")
    subprocess.run(["git", "add", "index.html"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "old deploy"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, check=True, capture_output=True)

    result = run_cli(tmp_path, "deploy-dashboard", "--no-push")

    assert result.returncode == 0, result.stderr
    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=tmp_path,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    deployed_html = subprocess.run(
        ["git", "show", "gh-pages:index.html"],
        cwd=tmp_path,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    assert current_branch == "main"
    assert "new dashboard" in deployed_html
