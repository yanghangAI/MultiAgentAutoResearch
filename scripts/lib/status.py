from __future__ import annotations

import re
from pathlib import Path

from scripts.lib import layout, results as results_service, store
from scripts.lib.models import Status


IDEA_HEADERS = ["Idea_ID", "Idea_Name", "Status"]
DESIGN_HEADERS = ["Design_ID", "Design_Description", "Status"]


def get_expected_designs(idea_id: str, root: Path | None = None) -> int | None:
    content = store.read_text(layout.idea_md_path(idea_id, root))
    if not content:
        return None
    match = re.search(r"\*\*Expected Designs:\*\*\s*(\d+)", content)
    if match:
        return int(match.group(1))
    return None


def add_idea(idea_id: str, idea_name: str, status: str = Status.NOT_DESIGNED, root: Path | None = None) -> None:
    csv_path = layout.idea_csv_path(root)
    store.ensure_csv(csv_path, IDEA_HEADERS)
    rows = store.read_csv_rows(csv_path)
    for row in rows[1:]:
        if row and row[0] == idea_id:
            print(f"Idea {idea_id} already exists.")
            return
    store.append_csv_row(csv_path, [idea_id, idea_name, status])
    print(f"Added idea {idea_id}.")


def update_idea(idea_id: str, status: str, root: Path | None = None) -> None:
    csv_path = layout.idea_csv_path(root)
    store.ensure_csv(csv_path, IDEA_HEADERS)
    rows = store.read_csv_rows(csv_path)
    updated = False
    for row in rows:
        if row and row[0] == idea_id:
            row[2] = status
            updated = True
    if not updated:
        print(f"Idea {idea_id} not found.")
        return
    store.write_csv_rows(csv_path, rows)
    print(f"Updated idea {idea_id} to '{status}'.")


def add_design(
    idea_id: str,
    design_id: str,
    description: str,
    status: str = Status.NOT_IMPLEMENTED,
    root: Path | None = None,
) -> None:
    csv_path = layout.design_csv_path(idea_id, root)
    store.ensure_csv(csv_path, DESIGN_HEADERS)
    rows = store.read_csv_rows(csv_path)
    for row in rows[1:]:
        if row and row[0] == design_id:
            print(f"Design {design_id} already exists in {idea_id}.")
            return
    store.append_csv_row(csv_path, [design_id, description, status])
    print(f"Added design {design_id} to {idea_id}.")


def update_design(idea_id: str, design_id: str, status: str, root: Path | None = None) -> None:
    csv_path = layout.design_csv_path(idea_id, root)
    if not csv_path.exists():
        print(f"CSV {csv_path} not found.")
        return
    rows = store.read_csv_rows(csv_path)
    updated = False
    changed = False
    for row in rows:
        if row and row[0] == design_id:
            if len(row) > 2 and row[2] != status:
                row[2] = status
                changed = True
            updated = True
    if not updated:
        print(f"Design {design_id} not found in {idea_id}.")
        return
    if changed:
        store.write_csv_rows(csv_path, rows)
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
    rows = store.read_csv_rows(layout.idea_csv_path(root))
    if not rows:
        print(f"CSV {layout.idea_csv_path(root)} not found.")
        return None
    for row in rows:
        if row and row[0] == idea_id:
            print(row[2])
            return row[2]
    print(f"Idea {idea_id} not found.")
    return None


def get_design_status(idea_id: str, design_id: str, root: Path | None = None) -> str | None:
    csv_path = layout.design_csv_path(idea_id, root)
    rows = store.read_csv_rows(csv_path)
    if not rows:
        print(f"CSV {csv_path} not found.")
        return None
    for row in rows:
        if row and row[0] == design_id:
            print(row[2])
            return row[2]
    print(f"Design {design_id} not found in {idea_id}.")
    return None


def get_ideas_by_status(status: str, root: Path | None = None) -> list[str]:
    found = [
        row[0]
        for row in store.read_csv_rows(layout.idea_csv_path(root))
        if row and len(row) > 2 and row[2] == status
    ]
    if found:
        print("\n".join(found))
    else:
        print(f"No ideas found with status '{status}'.")
    return found


def get_designs_by_status(idea_id: str, status: str, root: Path | None = None) -> list[str]:
    csv_path = layout.design_csv_path(idea_id, root)
    found = [
        row[0]
        for row in store.read_csv_rows(csv_path)
        if row and len(row) > 2 and row[2] == status
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
) -> str | None:
    if results_index is None:
        results_index = load_results_index(root)
    row = results_index.get((idea_id, design_id))
    if row:
        try:
            epoch = int(float(row.get("epoch", "0")))
        except ValueError:
            epoch = 0
        return Status.DONE if epoch >= 20 else Status.TRAINING

    design_path = layout.design_dir(idea_id, design_id, root)
    code_review = store.read_text(design_path / "code_review.md")
    if "APPROVED" in code_review:
        if list(design_path.glob("slurm_*.out")):
            return Status.SUBMITTED
        return Status.IMPLEMENTED

    review = store.read_text(design_path / "review.md")
    if "APPROVED" in review:
        return Status.NOT_IMPLEMENTED
    return None


def derive_idea_status(idea_id: str, root: Path | None = None) -> str | None:
    rows = store.read_csv_rows(layout.design_csv_path(idea_id, root))
    if len(rows) <= 1:
        return None
    current_designs = len(rows) - 1
    expected_designs = get_expected_designs(idea_id, root)
    has_all_designs = expected_designs is None or current_designs >= expected_designs

    statuses = [row[2] for row in rows[1:] if len(row) > 2]
    if not has_all_designs:
        return Status.NOT_DESIGNED
    if statuses and all(status == Status.DONE for status in statuses):
        return Status.DONE
    if statuses and all(status in {Status.TRAINING, Status.DONE} for status in statuses):
        return Status.TRAINING
    if statuses and all(
        status in {Status.IMPLEMENTED, Status.SUBMITTED, Status.TRAINING, Status.DONE}
        for status in statuses
    ):
        return Status.IMPLEMENTED
    return Status.DESIGNED


def auto_update_status(
    idea_id: str,
    design_id: str,
    root: Path | None = None,
    results_index: dict[tuple[str, str], dict[str, str]] | None = None,
) -> None:
    design_status = derive_design_status(
        idea_id,
        design_id,
        root=root,
        results_index=results_index,
    )
    if design_status:
        update_design(idea_id, design_id, design_status, root=root)

    idea_status = derive_idea_status(idea_id, root=root)
    if idea_status:
        update_idea(idea_id, idea_status, root=root)


def sync_all(root: Path | None = None) -> None:
    print("Running summarize_results...")
    results_service.summarize_results(root=root)

    idea_rows = store.read_csv_rows(layout.idea_csv_path(root))
    if len(idea_rows) <= 1:
        print("No ideas to sync.")
        return

    results_index = load_results_index(root)
    for idea_row in idea_rows[1:]:
        if not idea_row:
            continue
        idea_id = idea_row[0]
        if len(idea_row) > 2 and idea_row[2] == Status.DONE:
            continue
        design_rows = store.read_csv_rows(layout.design_csv_path(idea_id, root))
        for design_row in design_rows[1:]:
            if not design_row:
                continue
            design_id = design_row[0]
            if len(design_row) > 2 and design_row[2] == Status.DONE:
                continue
            auto_update_status(
                idea_id,
                design_id,
                root=root,
                results_index=results_index,
            )
    print("Sync complete.")
