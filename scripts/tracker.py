import csv
import os
import argparse
import subprocess
import re
from pathlib import Path

IDEA_CSV = "runs/idea_overview.csv"

def get_expected_designs(idea_id):
    idea_path = os.path.join("runs", idea_id, "idea.md")
    if os.path.exists(idea_path):
        with open(idea_path, "r", encoding='utf-8') as f:
            content = f.read()
            match = re.search(r'\*\*Expected Designs:\*\*\s*(\d+)', content)
            if match:
                return int(match.group(1))
    return None

def init_csv(file_path, headers):
    if not os.path.exists(file_path):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

def add_idea(idea_id, idea_name, status='Not Designed'):
    init_csv(IDEA_CSV, ['Idea_ID', 'Idea_Name', 'Status'])
    rows = []
    with open(IDEA_CSV, 'r', newline='') as f:
        reader = csv.reader(f)
        rows = list(reader)
    for r in rows[1:]:
        if r and r[0] == idea_id:
            print(f"Idea {idea_id} already exists.")
            return
    with open(IDEA_CSV, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([idea_id, idea_name, status])
    print(f"Added idea {idea_id}.")

def update_idea(idea_id, status):
    init_csv(IDEA_CSV, ['Idea_ID', 'Idea_Name', 'Status'])
    rows = []
    updated = False
    with open(IDEA_CSV, 'r', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0] == idea_id:
                row[2] = status
                updated = True
            rows.append(row)
    if updated:
        with open(IDEA_CSV, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        print(f"Updated idea {idea_id} to '{status}'.")
    else:
        print(f"Idea {idea_id} not found.")

def get_design_csv(idea_id):
    return f"runs/{idea_id}/design_overview.csv"

def add_design(idea_id, design_id, desc, status='Not Implemented'):
    csv_path = get_design_csv(idea_id)
    init_csv(csv_path, ['Design_ID', 'Design_Description', 'Status'])
    rows = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.reader(f)
        rows = list(reader)
    for r in rows[1:]:
        if r and r[0] == design_id:
            print(f"Design {design_id} already exists in {idea_id}.")
            return
    with open(csv_path, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([design_id, desc, status])
    print(f"Added design {design_id} to {idea_id}.")

def update_design(idea_id, design_id, status):
    csv_path = get_design_csv(idea_id)
    if not os.path.exists(csv_path):
        print(f"CSV {csv_path} not found.")
        return
    rows = []
    updated = False
    with open(csv_path, 'r', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0] == design_id:
                row[2] = status
                updated = True
            rows.append(row)
    if updated:
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        print(f"Updated design {design_id} in {idea_id} to '{status}'.")
    else:
        print(f"Design {design_id} not found in {idea_id}.")

def update_both(idea_id, design_id, idea_status, design_status):
    update_idea(idea_id, idea_status)
    update_design(idea_id, design_id, design_status)

def auto_update_status(idea_id, design_id):
    """Automatically determine and update the status of a specific design and its parent idea."""
    d_status = None
    
    # Check results.csv first
    results_path = "results.csv"
    if os.path.exists(results_path):
        with open(results_path, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('idea_id') == idea_id and row.get('design_id') == design_id:
                    try:
                        epoch = int(float(row.get('epoch', 0)))
                        if epoch >= 20:
                            d_status = "Done"
                        else:
                            d_status = "Training"
                    except ValueError:
                        d_status = "Training"
    
    # If not found in results.csv, fallback to checking review files
    if not d_status:
        design_dir = os.path.join("runs", idea_id, design_id)
        code_review_path = os.path.join(design_dir, "code_review.md")
        review_path = os.path.join(design_dir, "review.md")
        
        if os.path.exists(code_review_path):
            with open(code_review_path, 'r', encoding='utf-8') as f:
                if "APPROVED" in f.read():
                    d_status = "Implemented"

        # Check if slurm_*.out exists in the design directory indicating it's been submitted
        if d_status == 'Implemented':
            import glob
            if glob.glob(os.path.join(design_dir, 'slurm_*.out')):
                d_status = 'Submitted'
        
        if not d_status and os.path.exists(review_path):
            with open(review_path, 'r', encoding='utf-8') as f:
                if "APPROVED" in f.read():
                    d_status = "Not Implemented"
    
    if d_status:
        update_design(idea_id, design_id, d_status)
    
    # Re-evaluate the idea status based on the entire design_overview.csv
    csv_path = get_design_csv(idea_id)
    if os.path.exists(csv_path):
        with open(csv_path, 'r', newline='') as f:
            reader = csv.reader(f)
            rows = list(reader)
            
        expected_designs = get_expected_designs(idea_id)
        current_designs = len(rows) - 1 if len(rows) > 0 else 0
        has_all_designs = (expected_designs is None) or (current_designs >= expected_designs)
            
        if current_designs > 0:
            all_done = True
            all_training_or_more = True
            all_implemented_or_more = True
            for row in rows[1:]:
                if len(row) > 2:
                    st = row[2]
                    if st != "Done":
                        all_done = False
                    if st not in ["Training", "Done"]:
                        all_training_or_more = False
                    if st not in ["Implemented", "Training", "Done"]:
                        all_implemented_or_more = False
                else:
                    all_done = False
                    all_training_or_more = False
                    all_implemented_or_more = False
            
            if not has_all_designs:
                i_status = "Not Designed"
            elif all_done:
                i_status = "Done"
            elif all_training_or_more:
                i_status = "Training"
            elif all_implemented_or_more:
                i_status = "Implemented"
            else:
                i_status = "Designed"
                
            update_idea(idea_id, i_status)

def get_idea_status(idea_id):
    if not os.path.exists(IDEA_CSV):
        print(f"CSV {IDEA_CSV} not found.")
        return
    with open(IDEA_CSV, 'r', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0] == idea_id:
                print(row[2])
                return
    print(f"Idea {idea_id} not found.")

def sync_all():
    """Update all ideas and designs by first summarizing results and then calling auto_update_status."""
    print("Running summarize_results.py...")
    try:
        subprocess.run(["python", "scripts/summarize_results.py"], check=True)
    except Exception as e:
        print(f"Error running summarize_results.py: {e}")
        
    if not os.path.exists(IDEA_CSV):
        print(f"CSV {IDEA_CSV} not found.")
        return
        
    with open(IDEA_CSV, 'r', newline='') as f:
        idea_rows = list(csv.reader(f))
        
    if len(idea_rows) <= 1:
        print("No ideas to sync.")
        return
        
    for i, idea_row in enumerate(idea_rows):
        if i == 0 or not idea_row: continue
        idea_id = idea_row[0]
        idea_status = idea_row[2] if len(idea_row) > 2 else ""
        
        if idea_status == 'Done':
            continue
            
        design_csv_path = get_design_csv(idea_id)
        if os.path.exists(design_csv_path):
            with open(design_csv_path, 'r', newline='') as f:
                design_rows = list(csv.reader(f))
            
            for j, d_row in enumerate(design_rows):
                if j == 0 or not d_row: continue
                design_id = d_row[0]
                d_status = d_row[2] if len(d_row) > 2 else ""
                
                if d_status != 'Done':
                    auto_update_status(idea_id, design_id)
                    
    print("Sync complete.")

def get_design_status(idea_id, design_id):
    csv_path = get_design_csv(idea_id)
    if not os.path.exists(csv_path):
        print(f"CSV {csv_path} not found.")
        return
    with open(csv_path, 'r', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0] == design_id:
                print(row[2])
                return
    print(f"Design {design_id} not found in {idea_id}.")

def get_ideas_by_status(status):
    if not os.path.exists(IDEA_CSV):
        print(f"CSV {IDEA_CSV} not found.")
        return
    found = []
    with open(IDEA_CSV, 'r', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if row and len(row) > 2 and row[2] == status:
                found.append(row[0])
    if found:
        print("\n".join(found))
    else:
        print(f"No ideas found with status '{status}'.")

def get_designs_by_status(idea_id, status):
    csv_path = get_design_csv(idea_id)
    if not os.path.exists(csv_path):
        print(f"CSV {csv_path} not found.")
        return
    found = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if row and len(row) > 2 and row[2] == status:
                found.append(row[0])
    if found:
        print("\n".join(found))
    else:
        print(f"No designs found in {idea_id} with status '{status}'.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='action')

    p1 = subparsers.add_parser('add_idea')
    p1.add_argument('idea_id')
    p1.add_argument('idea_name')

    p2 = subparsers.add_parser('update_idea')
    p2.add_argument('idea_id')
    p2.add_argument('status')

    p3 = subparsers.add_parser('add_design')
    p3.add_argument('idea_id')
    p3.add_argument('design_id')
    p3.add_argument('desc')

    p4 = subparsers.add_parser('update_design')
    p4.add_argument('idea_id')
    p4.add_argument('design_id')
    p4.add_argument('status')

    p5 = subparsers.add_parser('get_idea_status')
    p5.add_argument('idea_id')

    p6 = subparsers.add_parser('get_design_status')
    p6.add_argument('idea_id')
    p6.add_argument('design_id')

    p7 = subparsers.add_parser('get_ideas_by_status')
    p7.add_argument('status')

    p8 = subparsers.add_parser('get_designs_by_status')
    p8.add_argument('idea_id')
    p8.add_argument('status')

    p9 = subparsers.add_parser('update_both')
    p9.add_argument('idea_id')
    p9.add_argument('design_id')
    p9.add_argument('idea_status')
    p9.add_argument('design_status')
    
    p10 = subparsers.add_parser('auto_sync')
    p10.add_argument('idea_id')
    p10.add_argument('design_id')

    p11 = subparsers.add_parser('sync_all')

    args = parser.parse_args()
    if args.action == 'add_idea':
        add_idea(args.idea_id, args.idea_name)
    elif args.action == 'update_idea':
        update_idea(args.idea_id, args.status)
    elif args.action == 'add_design':
        add_design(args.idea_id, args.design_id, args.desc)
    elif args.action == 'update_design':
        update_design(args.idea_id, args.design_id, args.status)
    elif args.action == 'get_idea_status':
        print(get_idea_status(args.idea_id))
    elif args.action == 'get_design_status':
        print(get_design_status(args.idea_id, args.design_id))
    elif args.action == 'get_ideas_by_status':
        print(get_ideas_by_status(args.status))
    elif args.action == 'get_designs_by_status':
        print(get_designs_by_status(args.idea_id, args.status))
    elif args.action == 'update_both':
        update_both(args.idea_id, args.design_id, args.idea_status, args.design_status)
    elif args.action == 'auto_sync':
        auto_update_status(args.idea_id, args.design_id)
    elif args.action == 'sync_all':
        sync_all()
    else:
        parser.print_help()
