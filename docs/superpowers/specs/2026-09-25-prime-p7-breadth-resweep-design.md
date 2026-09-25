# P7 breadth-first retry design

Date: 2026-09-25
Status: proposed from operator direction to revisit unresolved Levels 1 and 2 before deeper levels.

## Goal and scope

Run one new local OFFLINE pass over unresolved early levels. First attempt each game without a replay-verified Level 1 prefix once. Then attempt Level 2 once for each game whose highest replay-verified prefix is exactly Level 1, including games that newly pass Level 1 in this pass. A game already verified through the target level is skipped. The pass does not retry Level 3 or later and does not create an official scorecard.

At design time, eight games lack Level 1 and 13 of the existing Level-1 games lack Level 2. These are selection facts, not hard-coded game lists. The source of progress is `load_best_prefix()` against sealed, replay-verified, guest-cleaned runs, never a previous campaign's outcome label.

## Approaches considered

1. Reuse the old first/second round commands: small operational change, but their immutable campaign ledgers intentionally skip every prior attempt. Moving or clearing those ledgers would lose the retry boundary. Reject.
2. Call `make asterion-prime-p7-next` for each game: preserves per-game evidence for Level 2, but cannot start a game without a verified Level 1 prefix and has no breadth ledger. Reject as the overall pass.
3. Add a small operator-only breadth controller and a separate campaign ledger, reusing the existing sweep attempt and evidence functions. This preserves old runs and ledgers, gives one clear command and resumable selection, and is the chosen approach.

## Operator interface and ordering

- `make asterion-prime-p7-breadth-preflight` is zero-model and prints safe counts and game IDs selected for Level 1 and Level 2. It creates no game action or official card.
- `make asterion-prime-p7-breadth` builds an isolated wheel, loads the existing local ARC wheels, and runs a new operator-only controller. It requires no `GAME`, seed, token, or time arguments.
- Short aliases `make p7-breadth-preflight` and `make p7-breadth` call those same targets; user guidance shows the short names first.
- Level 1 candidates are sorted by canonical game ID and attempted first. After that phase finishes, recompute verified progress and form the sorted Level 2 queue. A newly solved Level 1 game can therefore join Level 2 in the same pass.
- Each `(game_id, target_level)` is attempted at most once in this new campaign. Previous unsolved attempts do not block this one pass. Re-running the command resumes from its new ledger and cannot spend again on a terminal entry.
- A new run has a distinct time-stamped run ID. Existing first/second round ledgers, run directories, and official scorecards are never modified.

## Controls and evidence

- The current level's human baseline limits newly dispatched actions; a higher-level attempt replays only its highest verified prior prefix before asking the model.
- Each game has a 30-minute wall-time limit and stops after 5 minutes without a new `arc.action`, including Level 1. There is no aggregate token or wall-time cap, matching the operator's previous breadth authorization. Every run reports input and output tokens separately; cached input remains included in input totals.
- Success requires an exact summary, sealed trace, replay verification, terminal level, and guest cleanup. Unsolved-at-cap and completed timeouts require their existing evidence checks. A no-action stall is a distinct non-success outcome and requires a hash-valid trace, matching game/seed/target level, valid usage, a 300-second supervisor receipt, action cap, and confirmed guest cleanup. Zero-action or malformed evidence that cannot bind to a unique run fails closed.
- A separate private ledger under `.asterion-private/prime-p7-live/` records schema, campaign identity, fixed controls, phase, and one entry per `(game_id, target_level)`. Entries move through `running` to a terminal outcome with run ID, action count, per-run token counts, stop reason, and evidence digests. State is written atomically. On resume, a terminal entry is revalidated; an interrupted `running` entry may finalize only from complete matching evidence, otherwise the campaign stops for manual audit and never automatically retries it.
- The campaign stops if guest cleanup, run identity, prefix replay, usage, ledger consistency, or evidence validation is uncertain. It does not promote a partially observed level transition to a success.

## Implementation boundary

Add a new controller in `tools/` and two Make targets. Reuse `SweepScheduler._attempt`, metadata and verified-prefix loaders, and existing summary/trace validators. Change `tools/run_prime_p7_sweep.py` only to separate the five-minute action-stall switch from the old second-round flag and validate Level-1 stalls; keep old first/second campaign schemas and results unchanged. Application and framework modules do not gain new credential or campaign knowledge.

## Verification

Focused `unittest` cases cover selection and phase ordering, new Level-1 success joining Level 2, per-pair deduplication on resume, unchanged old ledgers, human action and time controls, Level-1 no-action stall, malformed/zero-action evidence rejection, running-entry recovery, per-run token accounting, guest cleanup, and public-safe output. Run Ruff, docs check, installed-wheel zero-model preflight, then an independent code review. Only after those pass should the paid pass begin. Do not run a new official submission.
