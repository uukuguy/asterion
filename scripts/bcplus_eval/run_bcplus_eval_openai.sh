#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
RESOURCE_ROOT=${ASTERION_DCI_RESOURCE_ROOT:-$PROJECT_ROOT}
dataset="$RESOURCE_ROOT/data/bcplus_qa.jsonl"
corpus="$RESOURCE_ROOT/corpus/bc_plus_docs"
[ -f "$dataset" ] || { echo "Asterion DCI dataset is unavailable" >&2; exit 2; }
[ -d "$corpus" ] || { echo "Asterion DCI corpus is unavailable" >&2; exit 2; }
level="level3"
if (($# > 0)) && [[ "$1" != --* ]]; then level=$1; shift; fi
thinking_level=""
if (($# > 0)) && [[ "$1" != --* ]]; then thinking_level=$1; shift; fi
case "$level" in
  level0|level1|level2|level3|level4) ;;
  *) echo "Asterion DCI context level is invalid" >&2; exit 2 ;;
esac
case "$thinking_level" in
  ""|off|minimal|low|medium|high|xhigh) ;;
  *) echo "Asterion DCI thinking level is invalid" >&2; exit 2 ;;
esac
output_root="$PROJECT_ROOT/outputs/asterion/bcplus_eval/openai_${level}_concurrency10"
if [[ -n "$thinking_level" ]]; then output_root="${output_root}_thinking${thinking_level}"; fi
command=(uv run --project "$PROJECT_ROOT" asterion-dci benchmark --profile bcplus.openai --dataset "$dataset" --corpus "$corpus" --output-root "$output_root" --runtime-context-level "$level")
if [[ -n "$thinking_level" ]]; then command+=(--thinking-level "$thinking_level"); fi
command+=("$@")
exec "${command[@]}"
