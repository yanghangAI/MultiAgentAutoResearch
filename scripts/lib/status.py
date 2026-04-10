from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

from scripts.lib import layout, results as results_service, store
from scripts.lib.models import Status
from scripts.lib.project_config import ProjectConfig, load_project_config


IDEA_HEADERS = ["Idea_ID", "Idea_Name", "Status", "created_at", "updated_at"]
DESIGN_HEADERS = ["Design_ID", "Design_Description", "Status", "created_at", "updated_at"]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_bold_field(content: str, field_name: str) -> str | None:
    pattern = rf"\*\*{re.escape(field_name)}:\*\*\s*(.+)"
    match = re.search(pattern, content)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def infer_idea_name(idea_id: str, root: Path | None = None) -> str:
    content = store.read_text(layout.idea_md_path(idea_id, root))
    parsed = _parse_bold_field(content, "Idea Name")
    if parsed:
        return parsed
    return idea_id


def infer_design_description(idea_id: str, design_id: str, root: Path | None = None) -> str:
    content = store.read_text(layout.design_dir(idea_id, design_id, root) / "design.md")
    parsed = _parse_bold_field(content, "Design Description")
    if parsed:
        return parsed
    return design_id


def get_expected_designs(idea_id: str, root: Path | None = None) -> int | None:
    content = store.read_text(layout.idea_md_path(idea_id, root))
    if not content:
        return None
    match = re.search(r"\*\*Expected Designs:\*\*\s*(\d+)", content)
    if match:
        return int(match.group(1))
    return None


def add_idea(idea_id: str, idea_name: str, status: str = Status.NOT_DESIGNED, root: Path | None = None) -> None:
    if not re.fullmatch(r"idea\d{3}", idea_id):
        raise SystemExit(f"Invalid idea_id '{idea_id}'. Must match idea### (e.g. idea001).")
    csv_path = layout.idea_csv_path(root)
    store.ensure_csv(csv_path, IDEA_HEADERS)
    store.ensure_csv(layout.design_csv_path(idea_id, root), DESIGN_HEADERS)
    rows = store.read_dict_rows(csv_path)
    for row in rows:
        if row.get("Idea_ID") == idea_id:
            print(f"Idea {idea_id} already exists.")
            return
    now = _now()
    rows.append({"Idea_ID": idea_id, "Idea_Name": idea_name, "Status": status, "created_at": now, "updated_at": now})
    store.write_dict_rows(csv_path, IDEA_HEADERS, rows)
    print(f"Added idea {idea_id}.")


def register_missing_ideas(root: Path | None = None) -> None:
    csv_path = layout.idea_csv_path(root)
    store.ensure_csv(csv_path, IDEA_HEADERS)
    tracked_ids = {
        row.get("Idea_ID", "")
        for row in store.read_dict_rows(csv_path)
        if row.get("Idea_ID")
    }
    for idea_dir in sorted(layout.runs_dir(root).glob("idea*")):
        if not idea_dir.is_dir():
            continue
        idea_id = idea_dir.name
        if idea_id in tracked_ids:
            continue
        if not layout.idea_md_path(idea_id, root).exists():
            continue
        add_idea(idea_id, infer_idea_name(idea_id, root=root), root=root)
        tracked_ids.add(idea_id)


def update_idea(idea_id: str, status: str, root: Path | None = None) -> None:
    csv_path = layout.idea_csv_path(root)
    store.ensure_csv(csv_path, IDEA_HEADERS)
    rows = store.read_dict_rows(csv_path)
    updated = False
    changed = False
    for row in rows:
        if row.get("Idea_ID") == idea_id:
            if row.get("Status") != status:
                row["Status"] = status
                row["updated_at"] = _now()
                changed = True
            updated = True
    if not updated:
        print(f"Idea {idea_id} not found.")
        return
    if changed:
        store.write_dict_rows(csv_path, IDEA_HEADERS, rows)
        print(f"Updated idea {idea_id} to '{status}'.")


def add_design(
    idea_id: str,
    design_id: str,
    description: str | None = None,
    status: str = Status.NOT_IMPLEMENTED,
    root: Path | None = None,
) -> None:
    if not re.fullmatch(r"design\d{3}", design_id):
        raise SystemExit(f"Invalid design_id '{design_id}'. Must match design### (e.g. design001).")
    store.ensure_csv(layout.idea_csv_path(root), IDEA_HEADERS)
    csv_path = layout.design_csv_path(idea_id, root)
    store.ensure_csv(csv_path, DESIGN_HEADERS)
    layout.design_dir(idea_id, design_id, root).mkdir(parents=True, exist_ok=True)
    if description is None:
        description = infer_design_description(idea_id, design_id, root=root)
    rows = store.read_dict_rows(csv_path)
    for row in rows:
        if row.get("Design_ID") == design_id:
            print(f"Design {design_id} already exists in {idea_id}.")
            return
    now = _now()
    rows.append({"Design_ID": design_id, "Design_Description": description, "Status": status, "created_at": now, "updated_at": now})
    store.write_dict_rows(csv_path, DESIGN_HEADERS, rows)
    print(f"Added design {design_id} to {idea_id}.")


def register_missing_designs(root: Path | None = None) -> None:
    cfg = load_project_config(root)
    for idea_row in store.read_dict_rows(layout.idea_csv_path(root)):
        idea_id = idea_row.get("Idea_ID", "")
        if not idea_id:
            continue
        csv_path = layout.design_csv_path(idea_id, root)
        store.ensure_csv(csv_path, DESIGN_HEADERS)
        tracked_ids = {
            row.get("Design_ID", "")
            for row in store.read_dict_rows(csv_path)
            if row.get("Design_ID")
        }
        idea_dir = layout.idea_dir(idea_id, root)
        for design_dir in sorted(idea_dir.glob("design*")):
            if not design_dir.is_dir():
                continue
            design_id = design_dir.name
            if design_id in tracked_ids:
                continue
            if not (design_dir / "design.md").exists():
                continue
            review = store.read_text(design_dir / "design_review.md")
            if cfg.status.approved_token not in review:
                continue
            add_design(idea_id, design_id, root=root)
            tracked_ids.add(design_id)


def update_design(idea_id: str, design_id: str, status: str, root: Path | None = None) -> None:
    csv_path = layout.design_csv_path(idea_id, root)
    if not csv_path.exists():
        print(f"CSV {csv_path} not found.")
        return
    rows = store.read_dict_rows(csv_path)
    updated = False
    changed = False
    for row in rows:
        if row.get("Design_ID") == design_id:
            if row.get("Status") != status:
                row["Status"] = status
                row["updated_at"] = _now()
                changed = True
            updated = True
    if not updated:
        print(f"Design {design_id} not found in {idea_id}.")
        return
    if changed:
        store.write_dict_rows(csv_path, DESIGN_HEADERS, rows)
        print(f"Updated design {design_id} in {idea_id} to '{status}'.")


def update_both(
    idea_id: str,
    design_id: str,
    idea_status: str,
    design_status: str,
    root: Path | None = None,
) -> None:
    update_idea(idea_id, idea_status, root=root)
    update_design(idea_id, design_id, design_status, root=root)


def get_idea_status(idea_id: str, root: Path | None = None) -> str | None:
    rows = store.read_dict_rows(layout.idea_csv_path(root))
    if not rows:
        print(f"CSV {layout.idea_csv_path(root)} not found.")
        return None
    for row in rows:
        if row.get("Idea_ID") == idea_id:
            print(row.get("Status", ""))
            return row.get("Status")
    print(f"Idea {idea_id} not found.")
    return None


def get_design_status(idea_id: str, design_id: str, root: Path | None = None) -> str | None:
    csv_path = layout.design_csv_path(idea_id, root)
    rows = store.read_dict_rows(csv_path)
    if not rows:
        print(f"CSV {csv_path} not found.")
        return None
    for row in rows:
        if row.get("Design_ID") == design_id:
            print(row.get("Status", ""))
            return row.get("Status")
    print(f"Design {design_id} not found in {idea_id}.")
    return None


def get_ideas_by_status(status: str, root: Path | None = None) -> list[str]:
    found = [
        row["Idea_ID"]
        for row in store.read_dict_rows(layout.idea_csv_path(root))
        if row.get("Status") == status and row.get("Idea_ID")
    ]
    if found:
        print("\n".join(found))
    else:
        print(f"No ideas found with status '{status}'.")
    return found


def get_designs_by_status(idea_id: str, status: str, root: Path | None = None) -> list[str]:
    csv_path = layout.design_csv_path(idea_id, root)
    found = [
        row["Design_ID"]
        for row in store.read_dict_rows(csv_path)
        if row.get("Status") == status and row.get("Design_ID")
    ]
    if found:
        print("\n".join(found))
    else:
        print(f"No designs found in {idea_id} with status '{status}'.")
    return found


def load_results_index(root: Path | None = None) -> dict[tuple[str, str], dict[str, str]]:
    rows = store.read_dict_rows(layout.results_csv_path(root))
    return {(row.get("idea_id", ""), row.get("design_id", "")): row for row in rows}


def derive_design_status(
    idea_id: str,
    design_id: str,
    root: Path | None = None,
    results_index: dict[tuple[str, str], dict[str, str]] | None = None,
    cfg: ProjectConfig | None = None,
) -> str | None:
    if cfg is None:
        cfg = load_project_config(root)
    if results_index is None:
        results_index = load_results_index(root)
    row = results_index.get((idea_id, design_id))
    if row:
        progress_field = cfg.status.progress_field
        try:
            progress = int(float(row.get(progress_field, "0")))
        except ValueError:
            progress = 0
        return Status.DONE if progress >= cfg.status.done_value else Status.TRAINING

    design_path = layout.design_dir(idea_id, design_id, root)

    if (design_path / "training_failed.txt").exists():
        return Status.TRAINING_FAILED

    implement_failed = store.read_text(design_path / "implement_failed.md")
    if implement_failed.strip():
        return Status.IMPLEMENT_FAILED

    code_review = store.read_text(design_path / "code_review.md")
    if cfg.status.approved_token in code_review:
        submitted_path = design_path / "job_submitted.txt"
        if submitted_path.exists():
            age_hours = (time.time() - submitted_path.stat().st_mtime) / 3600
            if age_hours > cfg.status.submission_timeout_hours:
                return Status.SUBMISSION_STALE
            return Status.SUBMITTED
        return Status.IMPLEMENTED

    review = store.read_text(design_path / "design_review.md")
    if cfg.status.approved_token in review:
        return Status.NOT_IMPLEMENTED
    return None


def derive_idea_status(idea_id: str, root: Path | None = None) -> str | None:
    rows = store.read_dict_rows(layout.design_csv_path(idea_id, root))
    if not rows:
        return None
    current_designs = len(rows)
    expected_designs = get_expected_designs(idea_id, root)
    has_all_designs = expected_designs is None or current_designs >= expected_designs

    statuses = [row["Status"] for row in rows if row.get("Status")]
    if not has_all_designs:
        return Status.NOT_DESIGNED
    if statuses and all(s == Status.DONE for s in statuses):
        return Status.DONE
    if statuses and all(s in {Status.TRAINING, Status.DONE} for s in statuses):
        return Status.TRAINING
    if statuses and all(
        s in {Status.IMPLEMENTED, Status.SUBMITTED, Status.TRAINING, Status.DONE}
        for s in statuses
    ):
        return Status.IMPLEMENTED
    return Status.DESIGNED


def auto_update_status(
    idea_id: str,
    design_id: str,
    root: Path | None = None,
    results_index: dict[tuple[str, str], dict[str, str]] | None = None,
    cfg: ProjectConfig | None = None,
) -> None:
    design_status = derive_design_status(
        idea_id,
        design_id,
        root=root,
        results_index=results_index,
        cfg=cfg,
    )
    if design_status:
        update_design(idea_id, design_id, design_status, root=root)

    idea_status = derive_idea_status(idea_id, root=root)
    if idea_status:
        update_idea(idea_id, idea_status, root=root)


def sync_all(root: Path | None = None) -> None:
    print("Running summarize_results...")
    results_service.summarize_results(root=root)

    cfg = load_project_config(root)
    results_index = load_results_index(root)
    runs = layout.runs_dir(root)
    now = _now()

    # --- Rebuild idea and design CSVs from filesystem ---
    idea_rows: list[dict[str, str]] = []
    for idea_path in sorted(runs.glob("idea*")):
        if not idea_path.is_dir():
            continue
        idea_id = idea_path.name
        if not layout.idea_md_path(idea_id, root).exists():
            continue

        idea_name = infer_idea_name(idea_id, root=root)

        # Rebuild design CSV for this idea
        design_rows: list[dict[str, str]] = []
        for design_path in sorted(idea_path.glob("design*")):
            if not design_path.is_dir():
                continue
            design_id = design_path.name
            if not (design_path / "design.md").exists():
                continue
            review = store.read_text(design_path / "design_review.md")
            if cfg.status.approved_token not in review:
                continue

            description = infer_design_description(idea_id, design_id, root=root)
            design_status = derive_design_status(
                idea_id, design_id, root=root,
                results_index=results_index, cfg=cfg,
            )
            design_rows.append({
                "Design_ID": design_id,
                "Design_Description": description,
                "Status": design_status or Status.NOT_IMPLEMENTED,
                "created_at": now,
                "updated_at": now,
            })

        # Write design CSV
        store.ensure_csv(layout.design_csv_path(idea_id, root), DESIGN_HEADERS)
        store.write_dict_rows(layout.design_csv_path(idea_id, root), DESIGN_HEADERS, design_rows)

        # Derive idea status from rebuilt design rows
        idea_status = _derive_idea_status_from_rows(idea_id, design_rows, root=root)
        idea_rows.append({
            "Idea_ID": idea_id,
            "Idea_Name": idea_name,
            "Status": idea_status or Status.NOT_DESIGNED,
            "created_at": now,
            "updated_at": now,
        })

    # Write idea CSV
    store.ensure_csv(layout.idea_csv_path(root), IDEA_HEADERS)
    store.write_dict_rows(layout.idea_csv_path(root), IDEA_HEADERS, idea_rows)

    if not idea_rows:
        print("No ideas to sync.")
    print("Sync complete.")


def _derive_idea_status_from_rows(
    idea_id: str,
    design_rows: list[dict[str, str]],
    root: Path | None = None,
) -> str | None:
    if not design_rows:
        return None
    current_designs = len(design_rows)
    expected_designs = get_expected_designs(idea_id, root)
    has_all_designs = expected_designs is None or current_designs >= expected_designs

    statuses = [row["Status"] for row in design_rows if row.get("Status")]
    if not has_all_designs:
        return Status.NOT_DESIGNED
    if statuses and all(s == Status.DONE for s in statuses):
        return Status.DONE
    if statuses and all(s in {Status.TRAINING, Status.DONE} for s in statuses):
        return Status.TRAINING
    if statuses and all(
        s in {Status.IMPLEMENTED, Status.SUBMITTED, Status.TRAINING, Status.DONE}
        for s in statuses
    ):
        return Status.IMPLEMENTED
    return Status.DESIGNED
