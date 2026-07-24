#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
RESOURCE_ROOT=${ASTERION_DCI_RESOURCE_ROOT:-$PROJECT_ROOT}
dataset="$RESOURCE_ROOT/data/dci-bench/data/hotpotqa/test.jsonl"; corpus="$RESOURCE_ROOT/corpus/wiki_corpus"
[ -f "$dataset" ] || { echo "Asterion DCI dataset is unavailable" >&2; exit 2; }; [ -d "$corpus" ] || { echo "Asterion DCI corpus is unavailable" >&2; exit 2; }
command=(uv run --project "$PROJECT_ROOT" asterion-dci benchmark --profile qa.hotpotqa --dataset "$dataset" --corpus "$corpus"); command+=("$@"); exec "${command[@]}"
