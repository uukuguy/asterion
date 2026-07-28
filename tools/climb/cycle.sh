#!/usr/bin/env bash
set -euo pipefail

hypothesis_id="${1:?hypothesis id required}"
commit_range="${2:?commit range required}"
review="${3:?review verdict required}"

uv run python tools/climb/sync-state.py \
  "$hypothesis_id" \
  --commit-range "$commit_range" \
  --review "$review"
