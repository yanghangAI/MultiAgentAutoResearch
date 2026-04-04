import os
import glob
import csv
import re

def summarize_results():
    base_dir = "runs"
    # Find all metrics.csv files under the runs directory
    metrics_files = glob.glob(os.path.join(base_dir, "**", "metrics.csv"), recursive=True)
    
    results = []
    
    for file in metrics_files:
        # Ignore test_output metrics or other subfolders if we only want training metrics
        if "test_output" in file.split(os.sep):
            continue
            
        idea_id = "unknown"
        design_id = "unknown"
        
        # Extract idea and design from the path using regex
        match_idea_design = re.search(r'(idea\d+)[/\\](design\d+)', file)
        if match_idea_design:
            idea_id = match_idea_design.group(1)
            design_id = match_idea_design.group(2)
        elif 'baseline' in file.split(os.sep):
            idea_id = 'baseline'
            design_id = 'baseline'
        elif 'bs_probe_1080ti' in file.split(os.sep):
            # Optional: categorizing bs probes nicely
            idea_id = 'bs_probe_1080ti'
            bs_match = re.search(r'(bs_\d+)', file)
            design_id = bs_match.group(1) if bs_match else 'unknown'
        
        try:
            with open(file, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    last_row = rows[-1]
                    epoch = last_row.get('epoch')
                    train_mpjpe = last_row.get('train_mpjpe_weighted')
                    val_mpjpe = last_row.get('val_mpjpe_weighted')
                    
                    if train_mpjpe is not None or val_mpjpe is not None:
                        results.append({
                            'idea_id': idea_id,
                            'design_id': design_id,
                            'epoch': epoch,
                            'train_mpjpe_weighted': train_mpjpe,
                            'val_mpjpe_weighted': val_mpjpe
                        })
        except Exception as e:
            print(f"Error reading {file}: {e}")
            
    if results:
        # Sort by idea_id and design_id for orderly presentation
        results.sort(key=lambda x: (x['idea_id'], x['design_id']))
        
        out_file = "results.csv"
        with open(out_file, 'w', newline='') as f:
            fieldnames = ['idea_id', 'design_id', 'epoch', 'train_mpjpe_weighted', 'val_mpjpe_weighted']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
            
        print(f"Successfully summarized {len(results)} results into {out_file}")
    else:
        print("No valid training metrics.csv files found with the required metric columns.")

if __name__ == "__main__":
    summarize_results()
