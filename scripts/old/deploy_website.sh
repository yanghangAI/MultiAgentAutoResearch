#!/bin/bash
set -e

cd "$(dirname "$0")/../.." || exit 1
python scripts/cli.py build-dashboard
python scripts/cli.py deploy-dashboard "$@"
