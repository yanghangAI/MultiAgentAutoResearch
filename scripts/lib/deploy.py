from __future__ import annotations

import subprocess
import tempfile
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
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with tempfile.TemporaryDirectory(prefix="deploy-gh-pages-", dir=root_path) as temp_dir:
        worktree_path = Path(temp_dir)
        try:
            git(root_path, "worktree", "add", "--detach", str(worktree_path), "gh-pages")
            target_path = worktree_path / "index.html"
            target_path.write_text(html, encoding="utf-8")
            git(worktree_path, "add", "index.html")
            git(worktree_path, "diff", "--cached", "--quiet", capture_output=False)
            print("No dashboard changes to deploy.")
            return
        except subprocess.CalledProcessError as exc:
            if exc.returncode != 1:
                raise
            git(worktree_path, "commit", "-m", f"Auto-deploy website [{timestamp}]")
            deployed_rev = git(worktree_path, "rev-parse", "HEAD").stdout.strip()
            git(root_path, "branch", "-f", "gh-pages", deployed_rev)
            if push:
                git(worktree_path, "push", "origin", f"{deployed_rev}:refs/heads/gh-pages")
            print("Dashboard deployed to gh-pages.")
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=root_path,
                check=True,
                capture_output=True,
                text=True,
            )
