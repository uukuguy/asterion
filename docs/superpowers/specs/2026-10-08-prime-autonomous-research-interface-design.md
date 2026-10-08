# Autonomous research interface

Status: authorized implementation, not solving-capability evidence. Follows D-2026-10-08-02 and the [failed NOTES comparison](../../reviews/2026-10-08-p7-notes-bp35-comparison.md).

The LLM owns experiments, predictions, notes and strategy. The harness supplies exact observations, usable computation, recoverable evidence and genuine execution controls. No game-specific solution is injected.

## Generic responsibilities

- Prime keeps raw history intact and projects model history by capacity, independently of note writes. Trigger at 96 KiB model-bearing UTF-8 JSON, target 48 KiB; keep at most eight recent complete assistant/tool-result units, protect at least two and every pending sibling group. Pin actual user/system instructions. Indivisible protected content can exceed the budget; report that condition rather than truncate or forge messages.
- Trusted context snapshots refresh current state with or without notes. Private envelope v2 permits null revision only for non-commit state refresh. Only registered application tool results supply trusted metadata; computation stdout never does.
- `TaskDeadline` combines absolute monotonic and wall deadlines, expires permanently when either passes, and is never renewed by continuation or recovery. Clocks are injectable for tests. This is an execution boundary, not a reasoning schedule.

## P7 responsibilities

Modern operator runs select internal `autonomous` learner profile. Historical `legacy` and `notes` remain available for regression evidence. Keep the existing runner and three tools.

- Plan requires identity, current observation and ordered actions. Workspace revision may be omitted (host binds current), but a supplied revision must match. Goal, purpose, assumptions and predictions are optional. Missing predictions do not count as a match. Known prediction misses may continue only when the actor explicitly chooses; unknown effects, level changes, game-over, RESET, budget and cancellation stop the suffix.
- Notes and WorldMap are optional external understanding, never admission gates. Repeated coordinates, no-effect and novelty heuristics become observations rather than authority. A lost computation kernel does not invalidate current environment authority. Certified replay retains strict witnesses.
- Read-only research supports discoverable `import p7_research as r`, exact current/raw frames and bounded grid, geometry and difference helpers. All colors are data; no implicit game-specific background or hidden source/rules access. Model chooses how to investigate.
- Durable action intent precedes dispatch. The actual SDK adapter checks the shared deadline immediately before entry, after journal I/O. Unknown effects remain unresolved and prevent further actions after recovery; no automatic retry or RESET repairs them.
- The adapter preserves returned evidence under a separate fixed settlement ceiling (task deadline +180 seconds), without authorizing further effects. A compact transaction records prepared, entered, reply-received, committed, definitely-not-dispatched or unresolved outcomes. This does not claim general exactly-once execution or atomicity between user-space checks and external calls.
- Guest clock origins are minted in the guest domain. Operator writes minimal terminal status before expensive optional finalization. Sleep can delay scheduling; expired work must stop on resumption, not acquire a renewed budget.

## Verification boundary

Meaningful fake-clock, admission, observation and history tests; TypeScript tests, relevant Python tests, `make promotion-check`, then one packaged r11l L1 witness. No new BP35 benchmark in this package. Passing infrastructure tests or one small level cannot establish BP35 L5/L6 autonomy.
