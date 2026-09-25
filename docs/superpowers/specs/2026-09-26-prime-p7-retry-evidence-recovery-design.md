# P7 breadth failure evidence and targeted retry

Date: 2026-09-26
Status: authorized by the operator's request to diagnose, repair, and retry failed levels after the completed Level-1/Level-2 breadth sweep and one official batch submission.

## Observed problem

The breadth ledger contains four unsolved Level-1 attempts, eight unsolved Level-2 attempts, and four Level-2 execution stalls. The Level-2 attempts have three distinct evidence shapes. A Level-1 failure ends with `arc.run.failed`; a sealed Level-2 failure ends with `arc.run.partial` describing only the verified completed-level prefix; a supervisor stall has an unsealed trace and `stall-receipt.json`. The current retry reader admits only the first shape. G50T also has an older incomplete recording that currently poisons selection of its newer complete failure.

The official batch card is already closed. Every retry is OFFLINE, timestamped, and limited by the target level's human action baseline, 30 minutes, and five minutes without a new action. A retry never overwrites earlier runs or submits another scorecard.

## Approaches

1. Loosen the existing `arc.run.failed` check or silently skip malformed candidates. This would confuse prefix replay with full-run replay and could hide corrupted evidence.
2. **Chosen:** retain three explicit source types: `sealed-failure`, `sealed-partial-failure`, and `execution-stall-observation`. Validate each type's exact terminal contract, bind its action facts to the trace and recording, and label the replay scope in the advice. A matching malformed newest source fails closed; older incomplete sources cannot hide a newer complete source but are never included as facts.
3. Retry without prior evidence. This would repeat the behavior that failed BP35 and leave the four stalls unusable for diagnosis.

## Evidence boundary

The reader selects at most two recent sources for the exact game ID, seed, and target level from the operator's private run root. It checks regular paths, identities, a complete hash chain, contiguous action sequence, action data, state hashes, recorded settled frames and level counts, usage, and the level's human action cap. It never reads worker cells, prompts, credentials, or another game.

For a sealed partial run, the one `arc.run.partial` terminal event and `completed_prefix` must agree on the exact verified earlier-level prefix, including its replay digest and action count. The full failed attempt must agree with all trace and recording actions and the private broker terminal, but `replay_verified` proves only the completed prefix. Advice must say so; it cannot present all failed actions as independently replayed.

For a supervisor stall, receipt fields, cleanup, the exact final hash, allowed unsealed trace events, recording parity, historical verified prefix, target-level action count, and usage must match. It remains an observation, not a completed failed solve. A prefix-only stall explicitly reports zero target-level actions. An incomplete tail or ambiguous identity is rejected.

The source digest binds source type, run IDs, validated terminal or receipt, prefix identity, action facts, and token totals. Private retry diagnostics record that digest; public receipts expose only safe counts.

## Solver behavior and verification

On entering a later level, the solver may inspect saved history but should make no more than three startup history calls before forming one legal, falsifiable probe from the current settled frame. It may request further history after observing that probe. A failed history page counts toward the startup calls. This is prompt guidance, not an automatic game action, and it applies without game-specific coordinates or rules.

Focused zero-model tests cover valid and tampered examples of all three source types, matching/mismatching prefix and recording, incomplete G50T history selection, source digest binding, redaction, and the bounded startup instruction. Run only these tests and Ruff before a paid retry. First retry a short representative failed Level-1 game and a sealed Level-2 game to verify the reader and prompt in a real run; then retry eligible failed games once each, recording seal/replay/cleanup or exact stall reason. Do not infer general solving improvement from a single successful retry.
