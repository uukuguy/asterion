# P7 same-game failed-attempt learning design

Date: 2026-09-25
Status: approved in conversation for one BP35 Level-1 retry after zero-model verification.

## Purpose and limits

The operator observed two sealed BP35 Level-1 failures. Both spent seven clicks removing the same initial group of one color without a level transition. The new run must be able to see that verified negative evidence before spending actions. The behavior is game-agnostic: no game ID, color, coordinate, map, solution, or action sequence belongs in the permanent prompt or code. BP35 is only the acceptance example. The retry remains OFFLINE, uses seed 0, the human action baseline (21 for BP35 Level 1), a 30-minute attempt limit and a five-minute no-action limit. It creates one new run, leaves the earlier runs and breadth ledger unchanged, and makes no official submission.

## Approaches considered

1. Prompt-only reminders are small but cannot tell a new run what the previous same-game attempt disproved; the second BP35 attempt already repeated the first one's seven-click experiment. This is insufficient.
2. A bounded same-game failed-run fact bundle plus deterministic action-effect feedback is chosen. It reuses sealed local evidence and keeps the solver's reasoning game-agnostic. It does not claim a scene change is goal progress.
3. A full Retrodict-style executable world model, search and long-lived playbook would be wider than the demonstrated failure. A 300-action escalation cannot fire under BP35's 21-action human baseline. Defer it until small changes are evaluated.

## Evidence boundary and data flow

An application-owned reader selects at most the two most recent failed runs for the exact game ID, seed and target level. Sources must be under the operator's local P7 run root, be regular files with no symlink traversal, and have a matching private summary, sealed hash-valid trace, seal digest, replay_verified and cleanup_complete. The failure must be a genuine terminal such as `human-baseline` or `game-over`, with zero progress through the target level. An unsealed interrupted run (including CD82) is never eligible. The reader binds each trace action to the same run's recorded settled observation and checks identity, sequence, action data, state digest, level count and human action cap. It does not read worker cells, prompts, credentials or another game's run. Invalid candidates are rejected; a malformed selected source must not be silently promoted into advice.

Before starting the model, the P7 application builds a bounded, immutable fact block from the selected runs: source run ID, outcome, and up to 32 first plus 32 last target-level actions per run. For each included action it reports the action, level/state, interior and one-cell-border change counts, and settled-frame counts of the 16 canonical colors. If a run has at most 64 target-level actions, all appear once. These are observations, not inferred game rules or answer text. A digest binds the block to source traces. The same source IDs and digest are recorded privately in the new run's diagnostics. The public receipt reports only safe counts and the new result.

The model's input appends this block only for an explicitly requested same-game retry. The standard first-pass and official prompts do not acquire cross-run data. The instruction explains that repeated local effects are not proof of the goal, a completed-level increase is the authoritative progress signal, and a prior failed action sequence must not be repeated without a new falsifiable reason. The input identifies facts as checked observations and objectives as assumptions. The model may use the prior evidence to choose a different experiment, but the application does not hardcode that choice.

## Current-run feedback

The P7 worker's frame-difference helper continues to report all settled-cell changes and adds separate counts for interior and one-cell border changes. `border_only` means a hypothesis for HUD or timer activity, not a universal claim of a no-op, because some games use borders as gameplay. When a proposed action changes only the border, the prompt directs the solver to inspect the repeated pattern and avoid treating it as progress by itself. Before batching actions, it must separate a checked mechanic from an unverified objective and state the stop condition and remaining action budget. Repeating an ineffective action or exhausting a category of objects without a level increase should trigger re-evaluation, not another blind batch.

## Operator flow and improvement measurement

Add a short, explicit one-game command, `make p7-retry GAME=bp35`, that selects the next unresolved level (Level 1 for BP35) and invokes the existing supervised sweep attempt exactly once with 30-minute/5-minute/human-action controls. A retry marker passes only through the operator-owned environment into the guest application; it is never put into a manifest. The command writes a separate timestamped retry manifest with the selected prior run IDs and digest, new run ID, terminal status, action count, token totals and evidence result. It must not use or edit the paused breadth ledger. Another invocation is another paid retry and needs a new operator decision; it cannot silently repeat this one.

The post-run comparison is read-only and uses the two prior failed runs and the new run: completed levels, total actions, border-only actions, shared exact action inputs, distinct interior-frame digests, per-step interior change counts and tokens. It labels a result as an improvement only with observable support. Passing Level 1 is definitive improvement; a failed 21-step run can show changed exploration behavior but not solved capability. A newly passed level gets the existing sealed/replay-verified/cleaned success treatment and local report workflow.

## Verification

Use test-first focused `unittest` cases for exact-game selection, seal/summary/recording rejection, no symlink traversal, generic border/interior classification, prompt fact binding, one retry only, human/30-minute/5-minute controls, and private/public redaction. Run Ruff, docs check and an isolated installed-wheel zero-model preflight proving that both old BP35 failures are selected while CD82's interrupted run is excluded. Perform independent code review before the paid retry. The live test is one BP35 Level-1 attempt, followed by exact-run seal/replay/cleanup validation and a comparison against the two old attempts. Do not resume the breadth campaign in this task.
