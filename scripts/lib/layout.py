from __future__ import annotations

import re
from pathlib import Path


def repo_root(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root).resolve()
    return Path(__file__).resolve().parents[2]


def runs_dir(root: Path | None = None) -> Path:
    return repo_root(root) / "runs"


def idea_csv_path(root: Path | None = None) -> Path:
    return runs_dir(root) / "idea_overview.csv"


def design_csv_path(idea_id: str, root: Path | None = None) -> Path:
    return runs_dir(root) / idea_id / "design_overview.csv"


def results_csv_path(root: Path | None = None) -> Path:
    return repo_root(root) / "results.csv"


def website_dir(root: Path | None = None) -> Path:
    return repo_root(root) / "website"


def website_index_path(root: Path | None = None) -> Path:
    return website_dir(root) / "index.html"


def idea_dir(idea_id: str, root: Path | None = None) -> Path:
    return runs_dir(root) / idea_id


def design_dir(idea_id: str, design_id: str, root: Path | None = None) -> Path:
    return idea_dir(idea_id, root) / design_id


def idea_md_path(idea_id: str, root: Path | None = None) -> Path:
    return idea_dir(idea_id, root) / "idea.md"


def resolve_code_dir(path: Path) -> Path:
    path = Path(path)
    candidate = path / "code"
    if candidate.is_dir():
        return candidate
    return path


def resolve_train_script(path: Path) -> Path:
    path = Path(path)
    code_candidate = path / "code" / "train.py"
    if code_candidate.is_file():
        return code_candidate
    flat_candidate = path / "train.py"
    if flat_candidate.is_file():
        return flat_candidate
    return code_candidate


def parse_idea_design_from_metrics(metrics_path: Path) -> tuple[str, str]:
    parts = set(metrics_path.parts)
    match = re.search(r"(idea\d+)[/\\](design\d+)", str(metrics_path))
    if match:
        return match.group(1), match.group(2)
    if "baseline" in parts:
        return "baseline", "baseline"
    if "bs_probe_1080ti" in parts:
        bs_match = re.search(r"(bs_\d+)", str(metrics_path))
        return "bs_probe_1080ti", bs_match.group(1) if bs_match else "unknown"
    return "unknown", "unknown"


def parse_design_ref(path: Path) -> tuple[str, str] | None:
    parts = Path(path).parts
    for index, part in enumerate(parts):
        if part == "runs" and index + 2 < len(parts):
            idea_id = parts[index + 1]
            design_id = parts[index + 2]
            if idea_id.startswith("idea") and design_id.startswith("design"):
                return idea_id, design_id
    return None
