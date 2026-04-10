from __future__ import annotations

from html import escape
from math import isfinite
from pathlib import Path

from typing import TYPE_CHECKING

from scripts.lib import layout, store

if TYPE_CHECKING:
    from scripts.lib.context import ProjectContext


def _format_metric(value: object) -> str:
    raw = str(value).strip() if value else ""
    if not raw:
        return "N/A"
    try:
        num = float(raw)
    except (ValueError, TypeError):
        return "N/A"
    if not isfinite(num):
        return "N/A"
    return f"{num:.2f}"


def _is_baseline_result(cfg: object, idea_id: str, design_id: str) -> bool:
    return (idea_id, design_id) in set(cfg.dashboard.baseline_results)


def _github_blob_url(cfg: ProjectConfig, *parts: str) -> str:
    if not cfg.dashboard.github_repo_url:
        return "#"
    return f"{cfg.dashboard.github_repo_url}/blob/main/" + "/".join(parts)


def _github_tree_url(cfg: ProjectConfig, *parts: str) -> str:
    if not cfg.dashboard.github_repo_url:
        return "#"
    return f"{cfg.dashboard.github_repo_url}/tree/main/" + "/".join(parts)


def read_csv(path: Path) -> list[dict[str, str]]:
    return store.read_dict_rows(path)


def idea_excerpt(path: Path, limit: int = 200) -> str:
    content = store.read_text(path)
    if not content:
        return ""
    excerpt = content[:limit]
    if len(content) > limit:
        excerpt += "..."
    return escape(excerpt)


def build_context(ctx: ProjectContext) -> dict[str, object]:
    root_path = ctx.root
    cfg = ctx.cfg
    metric_fields = cfg.results.metric_fields
    metric_1 = metric_fields[0] if metric_fields else "metric_1"
    metric_2 = metric_fields[1] if len(metric_fields) > 1 else "metric_2"
    progress_field = cfg.status.progress_field
    ideas = read_csv(layout.idea_csv_path(root_path))
    results = read_csv(layout.results_csv_path(root_path))

    result_rows: list[dict[str, object]] = []
    for row in results:
        idea_id = row.get("idea_id", "")
        design_id = row.get("design_id", "")
        result_rows.append(
            {
                "idea_id": idea_id,
                "design_id": design_id,
                "progress": row.get(progress_field, ""),
                "metric_1_value": row.get(metric_1, "0"),
                "metric_2_value": row.get(metric_2, "0"),
                "metric_1_name": metric_1,
                "metric_2_name": metric_2,
                "is_baseline": _is_baseline_result(cfg, idea_id, design_id),
                "idea_url": _github_blob_url(cfg, "runs", idea_id, "idea.md"),
                "design_url": _github_blob_url(cfg, "runs", idea_id, design_id, "design.md"),
            }
        )

    idea_cards: list[dict[str, str]] = []
    for idea in ideas:
        idea_id = idea.get("Idea_ID", "")
        idea_cards.append(
            {
                "idea_id": idea_id,
                "idea_name": idea.get("Idea_Name", ""),
                "status": idea.get("Status", ""),
                "idea_url": _github_blob_url(cfg, "runs", idea_id, "idea.md"),
                "tree_url": _github_tree_url(cfg, "runs", idea_id),
                "excerpt": idea_excerpt(layout.idea_md_path(idea_id, root_path)),
            }
        )
    return {
        "results": result_rows,
        "ideas": idea_cards,
        "metric_1_name": metric_1,
        "metric_2_name": metric_2,
        "progress_field": progress_field,
        "repo_url": cfg.dashboard.github_repo_url,
    }


def render_dashboard(context: dict[str, object]) -> str:
    metric_1_name = str(context.get("metric_1_name", "metric_1"))
    metric_2_name = str(context.get("metric_2_name", "metric_2"))
    progress_label = str(context.get("progress_field", "epoch")).capitalize()
    repo_url = str(context.get("repo_url", ""))
    results_rows = context.get("results", [])
    idea_rows = context.get("ideas", [])
    if not isinstance(results_rows, list):
        results_rows = []
    if not isinstance(idea_rows, list):
        idea_rows = []

    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Multi-Agent Auto Research Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>body { padding-top: 2rem; background-color: #f8f9fa;} .idea-card { margin-bottom: 2rem; }</style>
</head>
<body>
    <div class="container">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1 class="mb-0">Multi-Agent Auto Research</h1>
"""
    if repo_url:
        html += (
            f'            <a href="{escape(repo_url)}" target="_blank" '
            'class="btn btn-outline-dark">View on GitHub</a>\n'
        )
    html += """
        </div>

        <h2 class="mt-5">Results Overview</h2>
        <div class="table-responsive">
            <table class="table table-striped table-hover mt-3 shadow-sm rounded" id="resultsTable">
                <thead class="table-dark">
                    <tr>
                        <th onclick="sortTable(0)" style="cursor: pointer;" title="Click to sort">Idea ID ↕</th>
                        <th onclick="sortTable(1)" style="cursor: pointer;" title="Click to sort">Design ID ↕</th>
"""
    html += (
        f'                        <th onclick="sortTable(2)" style="cursor: pointer;" '
        f'title="Click to sort">{escape(progress_label)} ↕</th>\n'
    )
    html += (
        f'                        <th onclick="sortTable(3)" style="cursor: pointer;" '
        f'title="Click to sort">{escape(metric_1_name)} ↕</th>\n'
        f'                        <th onclick="sortTable(4)" style="cursor: pointer;" '
        f'title="Click to sort">{escape(metric_2_name)} ↕</th>\n'
    )
    html += """
                    </tr>
                </thead>
                <tbody>
"""
    for row in results_rows:
        if not isinstance(row, dict):
            continue
        train_val = _format_metric(row["metric_1_value"])
        val_val = _format_metric(row["metric_2_value"])
        badge = ' <span class="badge bg-secondary">Baseline</span>' if row["is_baseline"] else ""
        tr_class = " class='table-secondary'" if row["is_baseline"] else ""
        html += (
            f"                    <tr{tr_class}>\n"
            f"                        <td><a href=\"{escape(str(row['idea_url']))}\" target=\"_blank\">"
            f"{escape(str(row['idea_id']))}</a></td>\n"
            f"                        <td><a href=\"{escape(str(row['design_url']))}\" target=\"_blank\">"
            f"{escape(str(row['design_id']))}</a>{badge}</td>\n"
            f"                        <td>{escape(str(row['progress']))}</td>\n"
            f"                        <td>{train_val}</td>\n"
            f"                        <td>{val_val}</td>\n"
            "                    </tr>\n"
        )

    html += """                </tbody>
            </table>
        </div>

        <h2 class="mt-5 mb-3">Ideas & Designs</h2>
        <div class="row">
"""
    for idea in idea_rows:
        if not isinstance(idea, dict):
            continue
        html += f"""
            <div class="col-md-6 idea-card">
                <div class="card h-100 shadow-sm">
                    <div class="card-body">
                        <h5 class="card-title text-primary"><a href="{escape(idea["idea_url"])}" target="_blank" style="text-decoration: none;">{escape(idea["idea_id"])}: {escape(idea["idea_name"])}</a></h5>
                        <h6 class="card-subtitle mb-2 text-muted">Status: {escape(idea["status"])}</h6>
                        <div class="card-text small"><pre style="white-space: pre-wrap;">{idea["excerpt"]}</pre></div>
                        <a href="{escape(idea["tree_url"])}" target="_blank" class="btn btn-sm btn-outline-primary mt-2">View Full Idea & Designs</a>
                    </div>
                </div>
            </div>
"""

    html += """        </div>
    </div>
    <footer class="text-center text-muted py-4 mt-4 border-top">
        <small>Powered by <a href="https://github.com/yanghangAI/MultiAgentAutoResearch" target="_blank">Multi-Agent Auto Research</a></small>
    </footer>
    <script>
    function sortTable(n) {
      var table, rows, switching, i, x, y, shouldSwitch, dir, switchcount = 0;
      table = document.getElementById("resultsTable");
      switching = true;
      dir = "asc";
      while (switching) {
        switching = false;
        rows = table.rows;
        for (i = 1; i < (rows.length - 1); i++) {
          shouldSwitch = false;
          x = rows[i].getElementsByTagName("TD")[n];
          y = rows[i + 1].getElementsByTagName("TD")[n];
          let xContent = x.innerText || x.textContent;
          let yContent = y.innerText || y.textContent;
          let xValue = isNaN(parseFloat(xContent)) ? xContent.toLowerCase() : parseFloat(xContent);
          let yValue = isNaN(parseFloat(yContent)) ? yContent.toLowerCase() : parseFloat(yContent);
          if (dir == "asc") {
            if (xValue > yValue) { shouldSwitch = true; break; }
          } else if (dir == "desc") {
            if (xValue < yValue) { shouldSwitch = true; break; }
          }
        }
        if (shouldSwitch) {
          rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
          switching = true;
          switchcount ++;
        } else if (switchcount == 0 && dir == "asc") {
          dir = "desc";
          switching = true;
        }
      }
    }
    </script>
</body>
</html>"""
    return html


def build_dashboard(ctx: ProjectContext) -> Path:
    root_path = ctx.root
    context = build_context(ctx)
    html = render_dashboard(context)
    output_path = layout.website_index_path(root_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Website generated successfully in '{output_path}'!")
    return output_path
