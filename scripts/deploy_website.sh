#!/bin/bash
set -e

# Get the current branch (just in case)
current_branch=$(git branch --show-current)

echo "1) Generating the website..."
python scripts/generate_website.py

echo "2) Committing current changes to main (results, runs, scripts)..."
git add results.csv runs/ scripts/
if ! git diff-index --quiet HEAD; then
    git commit -m "Auto-update results and scripts [$(date +'%Y-%m-%d %H:%M:%S')]"
    git push origin $current_branch
else
    echo "   No changes to commit to main."
fi

echo "3) Deploying to gh-pages branch..."
# Stash any other modifications just in case so checkout doesn't fail
git stash -q

git checkout gh-pages
cp website/index.html .
git add index.html

if ! git diff-index --quiet HEAD; then
    git commit -m "Auto-deploy website [$(date +'%Y-%m-%d %H:%M:%S')]"
    git push origin gh-pages
else
    echo "   No changes to index.html."
fi

# Go back to the original branch
git checkout $current_branch
git stash pop -q || true

echo "✅ Website successfully updated and pushed to GitHub!"
