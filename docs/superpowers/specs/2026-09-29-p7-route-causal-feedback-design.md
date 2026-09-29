# P7 Route Causal Feedback Design

## Goal

Turn a verified offline route shortening into generic, state-bound feedback that P7 can execute, validate, and use for replanning. A route optimization result must remain useful even when the model did not discover the shorter route itself.

## Scope

- Add generic causal certificates for route edits that preserve a verified terminal result.
- Capture the removed action, its route context, replay identity, and the proof that the edited route still succeeds.
- Inject bounded certificates into P7 prompts as executable hypotheses, with state and identity checks.
- Keep formal score submission separate: an optimized local route may be replayed through the existing official saved-submit path, but local evidence never becomes an official result automatically.

## Non-goals

- No BP35-specific action names, coordinates, or hard-coded route rules.
- No claim that a model autonomously discovered an offline-compressed route.
- No change to official scorecard authorization or credentials.

## Design

### Route compression proof

The optimizer returns a bounded tuple of compression proofs alongside the winning route. A proof may describe one of these generic edit classes:

- `delete`: a single action is dispensable;
- `replace`: a shorter action sequence preserves the verified result;
- `reorder`: equivalent neighboring actions can be reordered to remove a later edit;
- `collapse`: a detour, duplicate, or inverse-action subsequence can be removed as one edit.

The proof never asserts that an action is semantically useless from its name alone. It records:

- edit class and source route span;
- canonical actions before and after the edit;
- route identity `(game_id, seed)`;
- prefix and suffix action digests around the edit;
- baseline and candidate action counts;
- candidate replay result and terminal state.

The proof is accepted only when the baseline and candidate both pass the same replay oracle and the candidate is shorter. It is evidence of route-level causal dispensability, not a semantic claim about the game. If the oracle cannot distinguish why an edit works, the proof remains `verified-edit` and must not be promoted to a stronger semantic label.

### P7 integration

The operator serializes proofs into a bounded prompt section. The model is instructed to treat each proof as a hypothesis valid only at the matching state and identity, dispatch one action at a time through `p7_act_checked`, and abandon the hint on any digest or observation mismatch. The existing full-route hint remains available as a fallback, but proof metadata is explicit in diagnostics.

### Formal score boundary

The official saved-submit path remains the only route that can change a formal scorecard. A local optimized run records `unpromoted` evidence until that path is explicitly invoked. This keeps model-discovered, offline-optimized, replayed, and official results distinguishable.

## Verification

- Unit tests prove proof creation for deletion, replacement, reordering, and collapsed-subsequence cases, and reject mismatched identities or action counts.
- Prompt tests prove proofs contain no game-specific hard-coding and remain bounded.
- Operator tests prove proofs are injected only when the verified route source matches the live prefix.
- Existing P7 focused tests and lint remain passing.
