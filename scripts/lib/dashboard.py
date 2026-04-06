from __future__ import annotations

from html import escape
from pathlib import Path

from scripts.lib import layout, store
from scripts.lib.project_config import ProjectConfig, load_project_config


def _is_baseline_result(cfg: ProjectConfig, idea_id: str, design_id: str) -> bool:
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


def build_context(root: Path | None = None) -> dict[str, object]:
    root_path = layout.repo_root(root)
    cfg = load_project_config(root_path)
    metric_fields = cfg.results.metric_fields
    metric_1 = metric_fields[0] if metric_fields else "metric_1"
    metric_2 = metric_fields[1] if len(metric_fields) > 1 else "metric_2"
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
                "epoch": row.get("epoch", ""),
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
        "repo_url": cfg.dashboard.github_repo_url,
    }


def render_dashboard(context: dict[str, object]) -> str:
    metric_1_name = str(context.get("metric_1_name", "metric_1"))
    metric_2_name = str(context.get("metric_2_name", "metric_2"))
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
                        <th onclick="sortTable(2)" style="cursor: pointer;" title="Click to sort">Epoch ↕</th>
"""
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
        train_val = row["metric_1_value"] or "0"
        val_val = row["metric_2_value"] or "0"
        badge = ' <span class="badge bg-secondary">Baseline</span>' if row["is_baseline"] else ""
        tr_class = " class='table-secondary'" if row["is_baseline"] else ""
        html += (
            f"                    <tr{tr_class}>\n"
            f"                        <td><a href=\"{escape(str(row['idea_url']))}\" target=\"_blank\">"
            f"{escape(str(row['idea_id']))}</a></td>\n"
            f"                        <td><a href=\"{escape(str(row['design_url']))}\" target=\"_blank\">"
            f"{escape(str(row['design_id']))}</a>{badge}</td>\n"
            f"                        <td>{escape(str(row['epoch']))}</td>\n"
            f"                        <td>{float(train_val) if train_val else 0:.2f}</td>\n"
            f"                        <td>{float(val_val) if val_val else 0:.2f}</td>\n"
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


def build_dashboard(root: Path | None = None) -> Path:
    root_path = layout.repo_root(root)
    context = build_context(root_path)
    html = render_dashboard(context)
    output_path = layout.website_index_path(root_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Website generated successfully in '{output_path}'!")
    return output_path
