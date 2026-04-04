import csv
import json
import os
import glob

def read_csv(path):
    if not os.path.exists(path): return []
    with open(path, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))

def main():
    ideas = read_csv('runs/idea_overview.csv')
    results = read_csv('results.csv')
    
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoSapiens Project Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>body { padding-top: 2rem; background-color: #f8f9fa;} .idea-card { margin-bottom: 2rem; }</style>
</head>
<body>
    <div class="container">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1 class="mb-0">AutoSapiens Dashboard</h1>
            <a href="https://github.com/yanghangAI/autosapiens" target="_blank" class="btn btn-outline-dark">View on GitHub</a>
        </div>
        
        <h2 class="mt-5">Results Overview</h2>
        <div class="table-responsive">
            <table class="table table-striped table-hover mt-3 shadow-sm rounded" id="resultsTable">
                <thead class="table-dark">
                    <tr>
                        <th onclick="sortTable(0)" style="cursor: pointer;" title="Click to sort">Idea ID ↕</th>
                        <th onclick="sortTable(1)" style="cursor: pointer;" title="Click to sort">Design ID ↕</th>
                        <th onclick="sortTable(2)" style="cursor: pointer;" title="Click to sort">Epoch ↕</th>
                        <th onclick="sortTable(3)" style="cursor: pointer;" title="Click to sort">Train MPJPE ↕</th>
                        <th onclick="sortTable(4)" style="cursor: pointer;" title="Click to sort">Val MPJPE ↕</th>
                    </tr>
                </thead>
                <tbody>
"""
    for row in results:
        train_val = row.get('train_mpjpe_weighted', '0')
        val_val = row.get('val_mpjpe_weighted', '0')
        idea_id = row.get('idea_id', '')
        design_id = row.get('design_id', '')
        
        is_baseline = (idea_id == 'idea001' and design_id == 'design001') or (idea_id == 'idea002' and design_id == 'design001')
        badge = ' <span class="badge bg-secondary">Baseline</span>' if is_baseline else ''
        
        html += f"""                    <tr{" class='table-secondary'" if is_baseline else ""}>
                        <td><a href="https://github.com/yanghangAI/autosapiens/blob/main/runs/{idea_id}/idea.md" target="_blank">{idea_id}</a></td>
                        <td><a href="https://github.com/yanghangAI/autosapiens/blob/main/runs/{idea_id}/{design_id}/design.md" target="_blank">{design_id}</a>{badge}</td>
                        <td>{row.get('epoch', '')}</td>
                        <td>{float(train_val) if train_val else 0:.2f}</td>
                        <td>{float(val_val) if val_val else 0:.2f}</td>
                    </tr>
"""
    
    html += """                </tbody>
            </table>
        </div>

        <h2 class="mt-5 mb-3">Ideas & Designs</h2>
        <div class="row">
"""
    
    for idea in ideas:
        iid = idea.get('Idea_ID', '')
        name = idea.get('Idea_Name', '')
        status = idea.get('Status', '')
        
        md_path = f"runs/{iid}/idea.md"
        desc = ""
        if os.path.exists(md_path):
            with open(md_path, 'r', encoding='utf-8') as mf:
                content = mf.read()
                desc = content[:200].replace('\\n', '<br>') + "..."
                
        html += f"""
            <div class="col-md-6 idea-card">
                <div class="card h-100 shadow-sm">
                    <div class="card-body">
                        <h5 class="card-title text-primary"><a href="https://github.com/yanghangAI/autosapiens/blob/main/runs/{iid}/idea.md" target="_blank" style="text-decoration: none;">{iid}: {name}</a></h5>
                        <h6 class="card-subtitle mb-2 text-muted">Status: {status}</h6>
                        <div class="card-text small"><pre style="white-space: pre-wrap;">{desc}</pre></div>
                        <a href="https://github.com/yanghangAI/autosapiens/tree/main/runs/{iid}" target="_blank" class="btn btn-sm btn-outline-primary mt-2">View Full Idea & Designs</a>
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
        } else {
          if (switchcount == 0 && dir == "asc") {
            dir = "desc";
            switching = true;
          }
        }
      }
    }
    </script>
</body>
</html>"""

    os.makedirs('website', exist_ok=True)
    with open('website/index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("Website generated successfully in 'website/index.html'!")

if __name__ == '__main__':
    main()
