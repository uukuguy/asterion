# P7 Route Causal Feedback Design

## Goal

Turn a verified offline route shortening into generic, state-bound feedback that P7 can execute, validate, and use for replanning. A route optimization result must remain useful even when the model did not discover the shorter route itself.

## Scope

- Add generic, replay-verified compression records for route edits that preserve a target-level result.
- Capture the **joint edit**, baseline/candidate replay identities and per-step observation digests. A successful combined deletion never proves that each deletion works independently.
- Feed the compressed route and its bounded evidence into P7 with a state check before the first action and after each action.
- Record whether live execution followed, diverged from, or abandoned the optimized route.
- Keep formal score submission separate. A local optimized route becomes eligible for the existing saved-submit path only after a sealed local run actually reproduces it; local optimization alone never changes an official result.

## Non-goals

- No BP35-specific action names, coordinates, or hard-coded route rules.
- No claim that a model autonomously discovered an offline-compressed route.
- No change to official scorecard authorization or credentials.

## Design

### Route compression record

The optimizer returns one immutable compression record for the selected shorter route. Its structural edit class is `delete_span`, `replace_span`, `permute_then_delete`, or `composite`; contiguous multi-action deletion is `delete_span`, while noncontiguous deletion is `composite`. A reorder by itself is not a compression. The record includes the complete source and candidate action digests, ordered removed indices, optional replacement/reorder metadata, game ID, seed, target level, warmup digest, baseline and candidate counts, and terminal result.

The ARC replay oracle also returns a bounded sequence of observation digests with level and state, including the initial and warmup boundary observations. The optimizer requires fresh baseline and candidate replays, equal game/seed/target identity, a shorter candidate, and target completion. Equal observation digests are exact evidence of state convergence. Different digests do not prove semantic equivalence even if both routes reach the target; the record says only `route-level verified edit` in that case. An edit involving several removed actions remains one joint claim.

Candidate generation is finite and deterministic: existing arbitrary deletion and deletion-plus-replacement search is retained; contiguous deletion is classified as `delete_span`; adjacent permutation combined with at least one deletion is added within the same candidate and time budgets. No label such as `duplicate`, `inverse`, or `detour` is inferred without additional state evidence.

### P7 integration

The operator injects the verified candidate route plus a bounded evidence section only when the source route and live warmup prefix match exactly. The section identifies the joint edit and observed convergence points, and states what remains unknown. P7 is instructed to compare the live state digest to the expected candidate digest before and after each dispatched action, use `p7_act_checked` one action at a time, and abandon the route on any mismatch. The operator records `injected`, `followed_actions`, `first_divergence`, and `completed_target` from the actual trace, rather than claiming model adoption from prompt injection alone. No frame, private path, provider payload, or credential enters the prompt or public receipt.

### Formal score boundary

The official saved-submit path remains the only route that can change a formal scorecard. A sealed local live run that reproduces an optimized route is eligible for that existing path. The local optimizer's in-memory candidate and diagnostic metadata are not saved-submit artifacts. This keeps model-discovered, offline-optimized, live-reproduced, and official results distinguishable.

## Verification

- Unit tests prove structural edit classification for contiguous deletion, noncontiguous joint deletion, replacement with deletion, and permutation with deletion; identity and action-count mismatches are rejected.
- ARC fake-engine tests prove stable per-step digests and warmup boundary identity without exposing frames.
- Prompt tests prove the record contains no game-specific hard-coding and remains bounded.
- Operator tests prove injection only when the verified route source matches the live prefix, and diagnostics distinguish followed, divergence, and completed outcomes.
- Existing P7 focused tests and lint remain passing.
