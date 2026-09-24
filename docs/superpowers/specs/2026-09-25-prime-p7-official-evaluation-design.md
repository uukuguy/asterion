# P7 Full-Game and Official ARC-AGI-3 Evaluation Design

## Decision and authority

P7 is an ARC-AGI-3 solving application, not a first-level acceptance test. A
normal solve evaluates one complete selected game. A separate Competition
evaluation opens one official scorecard, attempts every environment returned by
the official SDK, closes the card, and retains the service's result and URL.
The user explicitly requested completion of P7's official solving submission
capability. The Competition scorecard is the first official submission route;
the Kaggle no-network agent package and Community Leaderboard pull request are
different submission systems and cannot be inferred from a scorecard.

`game_id` identifies a game definition. A live environment and its `guid` are
the game instance. `run_id` identifies Asterion evidence. `card_id` identifies
the official scorecard. None is interchangeable. A prior Asterion receipt is
not an engine checkpoint and cannot skip a level in a new local game.

## Public commands and outcomes

- `make asterion-prime-p7-games` remains read-only and lists exact local IDs,
  total levels, best verified progress, and whether a full-game win exists.
- `make asterion-prime-p7-solve GAME=ls20` starts a new local game, advances
  through all levels in order, and reports success only after the final SDK
  observation is `WIN` with `levels_completed == win_levels`. The default GAME
  is explicit in the help text. `LEVEL` is not a normal solve argument.
- A distinct development witness may stop at a specified level. Its receipt
  remains `unpromoted` and cannot count as full-game success or an official
  scorecard. Historical partial receipts and digests stay readable.
- `make asterion-prime-p7-official-preflight` is read-only: it checks the
  installed official SDK, exact model host closure, API key presence, account
  game list, bounded policy, and writable private evidence destination. It
  does not open a scorecard or call the model. It prints only safe readiness
  state and the game count.
- `make asterion-prime-p7-official-submit` is the explicit, potentially costly
  one-shot entry. It uses `OperationMode.COMPETITION` and records `card_id`,
  final server scorecard, and official scorecard URL. Submission means closing
  a scorecard with a server-confirmed result; Asterion must not claim a full
  game win if the server does not report one.

The official scorecard can contain partial or failed games. Its creation does
not prove that P7 solved them. The public summary separates the scorecard's
server status and score from each game's observed `WIN` and completed levels.

## Catalog and budget

The local game catalog reads only exact, validated `metadata.json` entries
under the operator-selected external ARC root. It never imports game source
during listing or selection. Full IDs are canonical; short aliases resolve
only when unique. The official catalog comes from the Competition SDK's
`get_environments()` and is bound to the preflight/submit attempt. Official
submission attempts all returned games, not only the two currently installed
locally. An unknown or changed ID fails before `make`.

Every game has a finite action, model-callback, and deadline budget. The action
ceiling is computed from official baseline actions when present:
`min(5000, max(1000, 2 * sum(baseline_actions)))`; without valid baselines it is
1000. This permits LS20's 776-action baseline while retaining an absolute
per-game cap. A session-wide cap is the sum of the fixed per-game ceilings.
The full vector of selected games and caps is sealed before opening the card.
Reaching a cap marks that game incomplete and proceeds according to the
Competition session policy. Controls are application-owned, never manifest
authority. No paid solve runs as part of verification.

## Game and scorecard lifecycle

The application owns a Competition session. After complete preflight, it
creates exactly one scorecard, then calls `make(game_id, scorecard_id=card_id)`
at most once for each official game. The first `reset()` starts that game and
captures its server `guid`; subsequent gameplay actions and `ACTION6(x,y)`
use the same instance. After a recoverable `GAME_OVER`, `RESET` restarts only
the current level. Completed levels remain monotonic. Normal game completion
requires SDK `WIN`, not merely a target-level counter.

Each game uses the P7 solver through an injected, narrow broker interface.
The framework runner receives resolved implementations and host services;
it never opens a scorecard, discovers games, selects a model, or stores
credentials. The operator owns game scheduling, the official SDK adapter,
credential injection, finite controls, and private evidence.

The session always attempts to close the opened scorecard once on orderly
completion or handled failure. If scorecard closure cannot be confirmed, it
records `recovery-required` with the private card ID and last known game/guid;
it never creates a replacement card automatically. An interrupted process
cannot reconstruct a local environment from an Asterion receipt. Official
remote continuation by saved guid is allowed only after a separate, tested
server-state reconciliation contract; it is not assumed here.

## Evidence and compatibility

The existing OFFLINE run still uses a fresh local engine to verify replay.
Competition mode must not make another environment for replay: official
observations, exact actions, monotonic sequences, identity, server `guid`,
and terminal SDK state form its live evidence. Its receipt carries an explicit
`official` mode and server-confirmed `card_id`/URL/result. No `replay_verified`
claim is made for remote execution. Private trace may hold action coordinates,
frames, model content, and exact server IDs; public output contains only
safe identities, status, aggregate counts, scores, and URL. Existing local
receipt schemas and past run directories are not rewritten.

The final scorecard response is authoritative for the official score. The
operator checks its card ID, returned game IDs, completion fields, and final
closed status before exposing the URL. Mismatch, missing fields, or a network
failure leaves an explicit unverified result. Official scorecard URL generation
never derives from a local receipt alone.

## Verification and delivery boundary

Use deterministic fake SDKs for full-game `WIN`, partial progress, failure and
reset, click coordinates, changed catalog, one-card/one-make enforcement,
closure failure, no-replay behavior, redaction, and server-result mismatch.
Test installed-wheel routing, lint, docs, and promotion without model calls or
an official card. An actual scorecard requires an operator-owned `ARC_API_KEY`,
model execution cost, and a one-shot Competition run; no credential is in the
current workspace. Report that boundary rather than labeling fake SDK tests
as an official submission.

Official Competition constraints are documented at
<https://docs.arcprize.org/toolkit/competition_mode>; the SDK game and
scorecard workflow is described at <https://docs.arcprize.org/full-play-test>.
