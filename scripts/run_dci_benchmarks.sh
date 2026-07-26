#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

exec uv run --project "$PROJECT_ROOT" \
  python "$PROJECT_ROOT/tools/run_dci_benchmarks.py" "$@"
