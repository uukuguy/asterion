# P7 Same-Game Level Reset Design

## Decision and scope

The user requested the official ARC-AGI-3 game lifecycle after identifying that
P7 closed the run at `GAME_OVER`. P7 continues to use the local `OFFLINE` SDK;
this change does not create an online Competition scorecard. The application
will keep one game instance alive across recoverable level failures and use
the SDK's `RESET` action to restart the current level. It will stop at the
selected target level or a finite operator limit.

The official Competition rules allow level resets but forbid a second
`make()` for the same environment. They do not provide a checkpoint API to
restore an ended local process. P7 must therefore retry within its current
live game. A new command still starts a new game at Level 1.

## Alternatives considered

1. **Same-instance `RESET` (chosen):** follows the SDK's current-level reset,
   preserves completed levels, and records failed actions and resets in the
   same attempt. It requires Broker, worker, and replay changes.
2. **Restart and replay old actions:** can reconstruct a local state only if
   every action deterministically reproduces it. It consumes actions in a new
   game, cannot continue the old Competition environment, and risks divergence.
3. **Serialize an engine snapshot:** would support cross-process continuation,
   but the public SDK has no supported save/load contract. This is separate
   future work, not a prerequisite for same-instance retry.

## Behavior

- At `GAME_OVER` before the target level, the Broker stops the current action
  batch and exposes the observation. The game instance remains available for
  one controlled `RESET`; ordinary gameplay actions are rejected until reset.
- A `RESET` uses the SDK's `GameAction.RESET` on that same instance. P7 permits
  it only after at least one gameplay action in the current level, preventing
  the SDK's zero-action full-game reset in `OFFLINE` mode. A proactive reset
  after a bad move is also allowed under that guard. `RESET` consumes one of
  P7's 500 primitive actions and is recorded in the private journal and trace.
- The same action path carries official `ACTION6` click data. Its data is exactly
  `{"x": int, "y": int}` with each coordinate in `0..63`; all other actions
  require empty data. The Broker journals canonical action data, the adapter
  passes it to the SDK, and fresh-engine replay verifies it. This closes the
  existing gap for `keyboard_click` games such as TU93.
- After reset, `levels_completed` must be unchanged and the state must return
  to active play. Any identity, level-count, or state mismatch fails closed.
  Previously completed levels are never reopened or silently discarded.
- If the 500-action cap is reached, the Broker closes even if the latest action
  caused `GAME_OVER`. Target-level completion takes priority when it occurs on
  the last permitted action. The model callback and deadline limits remain.
- The worker reports a recoverable `RESET_REQUIRED` result for `GAME_OVER`,
  explains the remaining budget, and can send `RESET`. It reports `ACTION_CAP`
  or `LEVEL_SOLVED` only at actual P7 stopping boundaries. The prompt directs
  the solver to reassess the reset level rather than replaying a losing plan.
- Replay starts a fresh engine, executes the complete journal including
  `RESET` and click coordinates, requires that only a reset follows `GAME_OVER`, verifies state
  digests and level monotonicity, and checks the final receipt. Score counts
  all actions taken on each completed level, including failed attempts and
  resets, matching the SDK's scorecard action accounting.
- If the model stops while a level is in `GAME_OVER`, a sealed failed receipt
  keeps its action count and terminal reason. If it stops while still active,
  the result remains unsuccessful without inventing a completed level.

## Boundaries and verification

The host and capability remain application-specific; generic framework
modules do not import ARC SDK code. No public receipt contains prompts,
frames, credentials, private paths, or raw worker output. Each attempt retains
an independent run directory.

Use deterministic fake engines to cover Level 1 completion, Level 2 failure,
`RESET` to Level 2, eventual target completion, proactive reset, invalid
zero-action reset, ordinary action after `GAME_OVER`, valid and invalid
`ACTION6` coordinates, budget exhaustion,
replay divergence, receipt score, and worker status. Verify the installed
wheel route without a model. Run lint, docs-check, and promotion-check. No
paid solve is required to verify the implementation boundary; a true LS20
multi-level result remains unverified until an authorized live run.
