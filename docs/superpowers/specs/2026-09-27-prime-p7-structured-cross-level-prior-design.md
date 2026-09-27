# P7 Structured Cross-Level Mechanics Prior

> Status: design approved by the user on 2026-09-27.

## Goal

After a verified prefix is replayed, P7 must carry forward evidence about the game's reusable interaction mechanics and use it to form the first hypothesis for the next level. The next level still needs a fresh observation and a falsifiable probe; a prior may not dictate its map, coordinates, or full action sequence.

## Scope

The first version covers one exact game ID and seed within one bounded run. It uses only broker history and retained observations. It does not share private state across games, inspect engine source, or change action caps, retry policy, or official submission behavior.

## Design

### Structured prior

Add an immutable, redacted prior view with:

- the verified prefix length and highest completed level;
- per-level action families and click-coordinate ranges, when present;
- per-level transition counts and level-advance boundaries;
- observed effect summaries derived from history records: changed-cell counts, sampled changed cells, no-effect counts, resets, and terminal/level-advance signals;
- reusable candidate rules expressed as evidence statements, each with the levels and sequences supporting it and a confidence class (`observed`, `repeated`, or `unconfirmed`).

The prior must never include prompts, credentials, raw provider payloads, private paths, or an unverified claim that a coordinate or route is universal.

### Model workflow

Expose the prior through the P7 client and render a compact prompt section. The prompt requires this order after entering a new level:

1. read status and the settled observation;
2. read the structured prior;
3. state one cross-level hypothesis and one level-specific uncertainty;
4. dispatch one low-risk current-level probe with a falsifiable expectation;
5. promote a rule only when the probe agrees; otherwise mark it contradicted, lower its confidence, and re-plan.

The current-level probe requirement applies only when the level is not already terminal. Prefix replay remains trusted and does not consume model reasoning turns.

### Evidence boundary

A changed frame is evidence of an effect, not proof of objective progress. Only an increased `levels_completed` or an authoritative terminal state proves progress. Rules inferred from one level are `unconfirmed`; repeated cross-level agreement is `repeated`. Contradictions must be visible to the model and must not be silently discarded.

### Failure handling

Prior extraction and rendering are bounded. If a page is unavailable or too large, return a safe empty/partial prior and keep the existing history API usable. A malformed prior fails closed before model execution. The existing no-effect guard, action cap, cancellation, cleanup, and redaction guarantees remain unchanged.

## Verification

Add focused tests for:

- deterministic extraction from synthetic multi-level history;
- action-family and coordinate normalization;
- confidence promotion and contradiction handling;
- prior immutability and redaction;
- prompt ordering and mandatory first current-level probe;
- empty/oversized history fallback;
- an offline fake Pi run proving the first post-prefix turn receives a prior and dispatches a bounded probe.

The live gate remains bounded. A successful live result requires a new action after the replayed prefix and an authoritative level increase; usage events or a stall receipt alone never count as progress.
