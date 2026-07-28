#!/usr/bin/env bash
# climb consult-ais.sh — Multi-AI parallel consult for decision gate
#
# Phase 1 STUB. Phase 3 fills with actual gemini / opencode CLI calls.
#
# Contract:
#   Input:
#     PROMPT       — decision-gate question (e.g. "should we push v0.25 with disaster B2?")
#     CONTEXT_FILE — path to context file (recent calibration / hypothesis / etc)
#   Output:
#     stdout JSON: {"claude": "PUSH|SKIP|PIVOT", "gemini": "...", "opencode": "...", "vote": "<majority>"}
#     Side effect: append entry to docs/status/climb/adjudicator-log.md
#   Exit code:
#     0 = all 3 consulted (even if some timeout, parse partial)
#     1 = >1 AI unreachable

set -euo pipefail

PROMPT="${PROMPT:-}"
CONTEXT_FILE="${CONTEXT_FILE:-}"

echo "[climb-consult] STUB. Phase 3 will run 3 AIs in parallel:"
echo "  { gemini -p \"\$PROMPT\" 2>&1 | head -10; } &"
echo "  { opencode chat \"\$PROMPT\" 2>&1 | head -10; } &"
echo "  (claude already inline)"
echo "  wait"
echo ""
echo "[climb-consult] Vote aggregation:"
echo "  3/3 PUSH → PUSH"
echo "  2/3 PUSH → PUSH (log 1 dissent)"
echo "  1/3 PUSH → SKIP this hypothesis"
echo "  3/3 SKIP → SKIP"
echo "  Tied → most conservative: SKIP > PIVOT > PUSH"
echo ""
echo "[climb-consult] Phase 1 stub returning placeholder:"
echo '{"claude": "PUSH", "gemini": "STUB", "opencode": "STUB", "vote": "PUSH"}'

exit 0
