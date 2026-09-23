# Prime P7 controlled game selection

## Goal

Select a supported, exact ARC-AGI-3 game and seed for the native P7 first-level solve without editing source for each run. Preserve the existing `ls20-9607627b` seed 0 default and prepare `tu93-0768757b` seed 0 as the next puzzle. This change does not run a model.

## Design

The operator owns `ASTERION_PRIME_P7_GAME_ID` and `ASTERION_PRIME_P7_SEED`. The Make preset forwards both to Orb. The installed application resolves them once during preflight into an immutable game selection. Selection is restricted to the two versions verified for P7's current name-only action protocol: `ls20-9607627b` and `tu93-0768757b`. Seed is a bounded nonnegative decimal integer. Preflight checks the selected game's exact local files and metadata under `ASTERION_PRIME_ARC_ROOT`; no online game discovery occurs.

The same selection is passed to the ARC engine, broker, fresh replay engine, sealed trace, private summary, and public receipt. The broker validates the engine identity before observation, accepts the selected game's level count, and seals the selected identity. Replay rejects a different identity before observation. A separate public selection receipt digest binds the game, seed, capability receipt digest, and broker replay digest without changing the closed capability receipt contract. The first-level partial score uses the official weighted-level denominator `N(N+1)/2` and the selected game's first-level human action baseline (22 for ls20, 19 for tu93). The run still stops after one completed level, with 500 primitive actions, 128 callbacks, and a one-hour deadline.

The run-story reader accepts the recording's positive level count, requires it to remain constant through the run, and includes that count in each observation hash. It checks the recording identity and broker summary against the sealed completion event, including the replay digest and action counts. Historical ls20 evidence with the original seven-level event format remains readable.

## Failure and evidence boundaries

Unknown IDs, malformed seeds, absent game files, mismatched metadata, mismatched replay identity, and unexpected level counts fail closed with public-safe reasons. The new setting grants no model, cost, or provider authority. Tests use fake engines and no model calls. The offline Orb check only constructs and resets the selected game, with zero actions. Actual solving remains a separately authorized live run.

## Alternatives considered

- Replacing the hardcoded ID with tu93 is smaller, but makes each later puzzle a source change and loses the ls20 preset.
- Allowing every local game would admit click games that the current P7 broker cannot execute and would make score inputs unverified.

The exact two-game selection avoids both problems and keeps the next run repeatable.
