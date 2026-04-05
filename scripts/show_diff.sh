#!/bin/bash

if [ -z "$1" ]; then
    echo "Usage: $0 <design_folder>"
    echo "Example: $0 runs/idea004/design001"
    exit 1
fi

DESIGN_DIR="${1%/}"

# Ensure it's idea004 or newer, or at least has a code/ subfolder
if [ ! -d "$DESIGN_DIR/code" ]; then
    echo "❌ Error: '$DESIGN_DIR/code' does not exist. This script is designed for idea004 and newer which use the 'code/' subdirectory structure."
    exit 1
fi

DESIGN_MD="$DESIGN_DIR/design.md"
if [ ! -f "$DESIGN_MD" ]; then
    echo "❌ Error: $DESIGN_MD not found."
    exit 1
fi

# Extract the explicitly stated starting point from design.md
STARTING_POINT=$(grep -ioE "starting point.*?((baseline/)|(runs/idea[0-9]+/design[0-9]+/))" "$DESIGN_MD" | grep -oE "(baseline/|runs/idea[0-9]+/design[0-9]+/)" | head -n 1 || true)

if [ -z "$STARTING_POINT" ]; then
    STARTING_POINT=$(grep -ioE "(baseline|runs/idea[0-9]+/design[0-9]+)" "$DESIGN_MD" | head -n 1 || true)
fi

STARTING_POINT="${STARTING_POINT%/}"

if [ -z "$STARTING_POINT" ]; then
    # Fallback to baseline
    STARTING_POINT="baseline"
    echo "⚠️ Auto-detect failed, defaulting starting point to: $STARTING_POINT"
else
    echo "🔍 Auto-detected starting point: $STARTING_POINT"
fi

# Resolve source code directory
if [ -d "$STARTING_POINT/code" ]; then
    SRC_CODE="$STARTING_POINT/code"
else
    SRC_CODE="$STARTING_POINT"
fi
DST_CODE="$DESIGN_DIR/code"

if [ ! -d "$SRC_CODE" ]; then
    echo "❌ Error: Starting point code directory '$SRC_CODE' does not exist."
    exit 1
fi

echo ""
echo "================================================================="
echo "💻 Comparing CODE changes (.py files only)"
echo " FROM: $SRC_CODE"
echo " TO:   $DST_CODE"
echo "================================================================="
echo ""

set +e
# Loop over python files in DST_CODE to cleanly compare
for pyfile in "$DST_CODE"/*.py; do
    filename=$(basename "$pyfile")
    if [ -f "$SRC_CODE/$filename" ]; then
        git --no-pager diff --no-index --color=always --diff-algorithm=histogram "$SRC_CODE/$filename" "$pyfile"
    else
        echo -e "\033[1;32m=== NEW FILE: $filename ===\033[0m"
    fi
done
set -e

