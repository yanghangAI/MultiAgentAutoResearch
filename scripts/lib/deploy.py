from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts.lib import layout


def git(root: Path, *args: str, capture_output: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=capture_output,
        check=True,
    )


def working_tree_dirty(root: Path) -> bool:
    result = git(root, "status", "--porcelain")
    return bool(result.stdout.strip())


def current_branch(root: Path) -> str:
    return git(root, "branch", "--show-current").stdout.strip()


def deploy_dashboard(root: Path | None = None, allow_dirty: bool = False, push: bool = True) -> None:
    root_path = layout.repo_root(root)
    source_path = layout.website_index_path(root_path)
    if not source_path.exists():
        raise SystemExit(f"Dashboard file not found: {source_path}")
    if working_tree_dirty(root_path) and not allow_dirty:
        raise SystemExit(
            "Refusing to deploy with a dirty git tree. "
            "Commit or stash changes first, or rerun with --allow-dirty."
        )

    html = source_path.read_text(encoding="utf-8")
    original_branch = current_branch(root_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        git(root_path, "checkout", "gh-pages")
        target_path = root_path / "index.html"
        target_path.write_text(html, encoding="utf-8")
        git(root_path, "add", "index.html")
        diff = git(root_path, "diff", "--cached", "--quiet", capture_output=False)
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 1:
            git(root_path, "commit", "-m", f"Auto-deploy website [{timestamp}]")
            if push:
                git(root_path, "push", "origin", "gh-pages")
            print("Dashboard deployed to gh-pages.")
        else:
            raise
    finally:
        if current_branch(root_path) != original_branch:
            git(root_path, "checkout", original_branch)
