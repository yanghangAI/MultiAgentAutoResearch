from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from scripts.lib.layout import repo_root
from scripts.lib.project_config import ProjectConfig, load_project_config


@dataclass(frozen=True)
class ProjectContext:
    """Immutable, per-invocation context. Created once at CLI entry."""

    root: Path
    _cfg_override: ProjectConfig | None = None

    @staticmethod
    def create(root: Path | None = None, cfg: ProjectConfig | None = None) -> ProjectContext:
        return ProjectContext(root=repo_root(root), _cfg_override=cfg)

    @cached_property
    def cfg(self) -> ProjectConfig:
        if self._cfg_override is not None:
            return self._cfg_override
        return load_project_config(self.root)

    @cached_property
    def results_index(self) -> dict[tuple[str, str], dict[str, str]]:
        from scripts.lib import store, layout
        rows = store.read_dict_rows(layout.results_csv_path(self.root))
        return {(r.get("idea_id", ""), r.get("design_id", "")): r for r in rows}
