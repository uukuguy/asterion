#!/usr/bin/env bash
# Provenance: upstream-github github:DCI-Agent/DCI-Agent-Lite@271f37e71f053bf0c99c05ce6d2fb53b841d922e
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
RESOURCE_ROOT=${ASTERION_DCI_RESOURCE_ROOT:-$PROJECT_ROOT}
dataset="$RESOURCE_ROOT/data/dci-bench/data/bright_economics/economics_full.jsonl"; corpus="$RESOURCE_ROOT/corpus/bright_corpus/economics"
[ -f "$dataset" ] || { echo "Asterion DCI dataset is unavailable" >&2; exit 2; }; [ -d "$corpus" ] || { echo "Asterion DCI corpus is unavailable" >&2; exit 2; }
command=(uv run --project "$PROJECT_ROOT" asterion-dci benchmark --profile bright.economics --dataset "$dataset" --corpus "$corpus"); command+=("$@"); exec "${command[@]}"
