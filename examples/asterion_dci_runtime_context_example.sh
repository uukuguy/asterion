#!/usr/bin/env bash

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  source "$PROJECT_ROOT/.env"
  set +a
fi

set -euo pipefail

: "${DCI_PROVIDER:?Set DCI_PROVIDER in .env}"
: "${DCI_MODEL:?Set DCI_MODEL in .env}"

level="${1:-high}"
QUESTION="Read the files in the current directory. Do not use web search. Use rg instead of grep when searching. Question: In the Bonang Matheba interview where the third-to-last question asks about the origin of the name given to her by radio listeners, what is the interviewer's first name? Answer with just the first name and one supporting file path."
if [ -n "${ASTERION_DCI_CORPUS_ROOT:-}" ] && [ "${ASTERION_DCI_CORPUS_ROOT#/}" = "$ASTERION_DCI_CORPUS_ROOT" ]; then
  printf 'ASTERION_DCI_CORPUS_ROOT must be an absolute path\n' >&2
  exit 2
fi
CORPUS_ROOT="${ASTERION_DCI_CORPUS_ROOT:-$PROJECT_ROOT/corpus}"
CORPUS_DIR="$CORPUS_ROOT/bc_plus_docs"
if [ ! -d "$CORPUS_DIR" ]; then
  printf 'Asterion DCI corpus directory does not exist: %s\n' "$CORPUS_DIR" >&2
  exit 2
fi

cd "$PROJECT_ROOT"
uv run asterion-dci run \
  --cwd "$CORPUS_DIR" \
  --tools read,bash \
  --max-turns 6 \
  --thinking-level "$level" \
  --eval-answer "Adaku" \
  "$QUESTION"
