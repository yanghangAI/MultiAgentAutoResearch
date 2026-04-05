#!/bin/bash

if [ -z "$1" ]; then
    echo "Usage: $0 <design_folder> [starting_point_folder]"
    echo "Example: $0 runs/idea001/design001"
    echo "         $0 runs/idea002/design001 runs/idea001/design001"
    exit 1
fi

DESIGN_DIR="${1%/}"
STARTING_POINT="${2%/}"

if [ -z "$STARTING_POINT" ]; then
    DESIGN_MD="$DESIGN_DIR/design.md"
    if [ -f "$DESIGN_MD" ]; then
        EXTRACTED=$(grep -ioE "starting point.*?((baseline)|(runs/idea[0-9]+/design[0-9]+))" "$DESIGN_MD" | grep -oE "(baseline|runs/idea[0-9]+/design[0-9]+)" | head -n 1 || true)
        
        if [ -n "$EXTRACTED" ]; then
            STARTING_POINT="$EXTRACTED"
            echo "🔍 Auto-detected starting point from design.md: $STARTING_POINT"
        else
            STARTING_POINT="baseline"
            echo "⚠️ Starting point not explicitly found in design.md, defaulting to: $STARTING_POINT"
        fi
    else
        STARTING_POINT="baseline"
        echo "⚠️ design.md not found, defaulting starting point to: $STARTING_POINT"
    fi
fi

# Ensure both paths exist
if [ ! -d "$STARTING_POINT" ]; then
    echo "❌ Error: Starting point directory '$STARTING_POINT' does not exist."
    exit 1
fi

if [ ! -d "$DESIGN_DIR" ]; then
    echo "❌ Error: Design directory '$DESIGN_DIR' does not exist."
    exit 1
fi

# Determine exactly where the python files live
if [ -d "$STARTING_POINT/code" ]; then
    SRC_CODE="$STARTING_POINT/code"
else
    SRC_CODE="$STARTING_POINT"
fi

if [ -d "$DESIGN_DIR/code" ]; then
    DST_CODE="$DESIGN_DIR/code"
else
    DST_CODE="$DESIGN_DIR"
fi

echo ""
echo "================================================================="
echo "Comparing CODE changes (.py files only):"
echo " FROM: $SRC_CODE"
echo " TO:   $DST_CODE"
echo "================================================================="
echo ""

# To do a clean diff of only python files, we can loop over the python files
# and use git diff on them individually for nice colored output
for pyfile in "$DST_CODE"/*.py; do
    filename=$(basename "$pyfile")
    if [ -f "$SRC_CODE/$filename" ]; then
        git --no-pager diff --no-index --color=always --diff-algorithm=histogram "$SRC_CODE/$filename" "$pyfile" || true
    else
        echo -e "\033[1;32m=== NEW FILE: $filename ===\033[0m"
        cat "$pyfile"
        echo ""
    fi
done

