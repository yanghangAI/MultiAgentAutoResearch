from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scripts.lib import layout


CONFIG_FILENAME = ".automation.json"


@dataclass(frozen=True)
class OutputPatchConfig:
    enabled: bool = False
    target_file: str = "config.py"
    regex: str = r'(output_dir\s*=\s*)["\'].*?["\']'
    replacement_template: str = r'\g<1>"{dst}"'


@dataclass(frozen=True)
class SetupDesignConfig:
    source_globs: tuple[str, ...] = ("*.py",)
    destination_subdir: str = "code"
    output_patch: OutputPatchConfig = OutputPatchConfig()


@dataclass(frozen=True)
class ResultsConfig:
    metric_fields: tuple[str, ...] = ("train_mpjpe_weighted", "val_mpjpe_weighted")
    primary_metric: str = "val_mpjpe_weighted"
    metrics_glob: str = "**/metrics.csv"
    exclude_path_parts: tuple[str, ...] = ("test_output",)


@dataclass(frozen=True)
class StatusConfig:
    progress_field: str = "epoch"
    done_value: int = 20
    approved_token: str = "APPROVED"
    submission_timeout_hours: float = 48.0


@dataclass(frozen=True)
class SubmitConfig:
    max_jobs_default: int = 30
    job_count_command: str = ""
    submit_train_command_template: str = ""
    submit_test_command_template: str = ""


@dataclass(frozen=True)
class DashboardConfig:
    github_repo_url: str = ""
    baseline_results: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class IntegrityConfig:
    immutable_paths: tuple[str, ...] = ("infra/**",)


@dataclass(frozen=True)
class ProjectConfig:
    results: ResultsConfig = ResultsConfig()
    status: StatusConfig = StatusConfig()
    setup_design: SetupDesignConfig = SetupDesignConfig()
    submit: SubmitConfig = SubmitConfig()
    dashboard: DashboardConfig = DashboardConfig()
    integrity: IntegrityConfig = IntegrityConfig()


def _as_tuple_str(values: object, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, list):
        return fallback
    out = [str(item) for item in values if isinstance(item, (str, int, float))]
    return tuple(out) if out else fallback


def _parse_baseline_results(values: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(values, list):
        return ()
    out: list[tuple[str, str]] = []
    for item in values:
        if isinstance(item, list) and len(item) == 2:
            out.append((str(item[0]), str(item[1])))
    return tuple(out)


def _load_raw_config(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        return {}
    raw_text = config_path.read_text(encoding="utf-8").strip()
    if not raw_text:
        return {}
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"Invalid {CONFIG_FILENAME}. Use JSON-compatible YAML content. Error: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid {CONFIG_FILENAME}: top-level object must be a mapping.")
    return data


def load_project_config(root: Path | None = None) -> ProjectConfig:
    root_path = layout.repo_root(root)
    data = _load_raw_config(root_path / CONFIG_FILENAME)

    results_data = data.get("results", {})
    status_data = data.get("status", {})
    setup_data = data.get("setup_design", {})
    submit_data = data.get("submit", {})
    dashboard_data = data.get("dashboard", {})
    integrity_data = data.get("integrity", {})

    if not isinstance(results_data, dict):
        results_data = {}
    if not isinstance(status_data, dict):
        status_data = {}
    if not isinstance(setup_data, dict):
        setup_data = {}
    if not isinstance(submit_data, dict):
        submit_data = {}
    if not isinstance(dashboard_data, dict):
        dashboard_data = {}
    if not isinstance(integrity_data, dict):
        integrity_data = {}

    output_patch_data = setup_data.get("output_patch", {})
    if not isinstance(output_patch_data, dict):
        output_patch_data = {}

    output_patch = OutputPatchConfig(
        enabled=bool(output_patch_data.get("enabled", False)),
        target_file=str(output_patch_data.get("target_file", "config.py")),
        regex=str(output_patch_data.get("regex", OutputPatchConfig.regex)),
        replacement_template=str(
            output_patch_data.get(
                "replacement_template",
                OutputPatchConfig.replacement_template,
            )
        ),
    )

    if data:
        if "metric_fields" not in results_data:
            raise SystemExit(
                f"Missing required field 'results.metric_fields' in {CONFIG_FILENAME}."
            )
        if "primary_metric" not in results_data:
            raise SystemExit(
                f"Missing required field 'results.primary_metric' in {CONFIG_FILENAME}."
            )

    return ProjectConfig(
        results=ResultsConfig(
            metric_fields=_as_tuple_str(
                results_data.get("metric_fields"),
                ResultsConfig.metric_fields,
            ),
            primary_metric=str(
                results_data.get("primary_metric", ResultsConfig.primary_metric)
            ),
            metrics_glob=str(results_data.get("metrics_glob", ResultsConfig.metrics_glob)),
            exclude_path_parts=_as_tuple_str(
                results_data.get("exclude_path_parts"),
                ResultsConfig.exclude_path_parts,
            ),
        ),
        status=StatusConfig(
            progress_field=str(status_data.get("progress_field", StatusConfig.progress_field)),
            done_value=int(status_data.get("done_value", status_data.get("done_epoch", StatusConfig.done_value))),
            approved_token=str(
                status_data.get("approved_token", StatusConfig.approved_token)
            ),
            submission_timeout_hours=float(
                status_data.get("submission_timeout_hours", StatusConfig.submission_timeout_hours)
            ),
        ),
        setup_design=SetupDesignConfig(
            source_globs=_as_tuple_str(
                setup_data.get("source_globs"),
                SetupDesignConfig.source_globs,
            ),
            destination_subdir=str(
                setup_data.get("destination_subdir", SetupDesignConfig.destination_subdir)
            ),
            output_patch=output_patch,
        ),
        submit=SubmitConfig(
            max_jobs_default=int(
                submit_data.get("max_jobs_default", SubmitConfig.max_jobs_default)
            ),
            job_count_command=str(
                submit_data.get("job_count_command", SubmitConfig.job_count_command)
            ),
            submit_train_command_template=str(
                submit_data.get(
                    "submit_train_command_template",
                    SubmitConfig.submit_train_command_template,
                )
            ),
            submit_test_command_template=str(
                submit_data.get(
                    "submit_test_command_template",
                    SubmitConfig.submit_test_command_template,
                )
            ),
        ),
        dashboard=DashboardConfig(
            github_repo_url=str(
                dashboard_data.get("github_repo_url", DashboardConfig.github_repo_url)
            ),
            baseline_results=_parse_baseline_results(
                dashboard_data.get("baseline_results")
            ),
        ),
        integrity=IntegrityConfig(
            immutable_paths=_as_tuple_str(
                integrity_data.get("immutable_paths"),
                IntegrityConfig.immutable_paths,
            ),
        ),
    )
