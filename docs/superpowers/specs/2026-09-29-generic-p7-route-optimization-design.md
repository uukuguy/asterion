# Generic P7 Action Feedback and Route Optimization Design

## Goal

Give every P7 level a bounded, semantic view of action effects and an offline
way to search for shorter verified action routes, without embedding a game ID,
coordinate, map, prompt fragment, or game-specific rule in the framework.

The online broker remains the only authority that can execute actions, enforce
caps, record traces, and seal replay evidence. Optimization proposes candidates
and never changes primitive action accounting.

## Constraints

- Framework code remains game-neutral; no BP35-specific constants or routes.
- `ArcBroker` continues to own action validation, caps, terminal handling,
  no-effect guards, journaling, and replay identity.
- `ArcadeEngine` remains an ARC SDK adapter and does not contain planning logic.
- Optimizer execution is offline and explicit; it never contacts a provider,
  reads credentials, or submits an official score.
- Public model feedback is bounded and payload-safe. It exposes semantic frame
  deltas, not hidden model reasoning, credentials, prompts, or private paths.
- A batch still costs one primitive action per submitted gameplay action.

## Design

### 1. Bounded action feedback

`ArcHistoryRecord` already computes changed-cell counts, sampled changes, frame
digests, level count, and state. The operator facade will project that evidence
into a compact `feedback` object on action results:

```json
{
  "changed_cell_count": 12,
  "changed_cells": [[3, 4, 0, 9]],
  "changed_cells_omitted": 0,
  "before_frame_sha256": "sha256:...",
  "after_frame_sha256": "sha256:...",
  "levels_completed": 0,
  "state": "NOT_FINISHED",
  "no_effect": false,
  "stop_reason": "matched"
}
```

The existing full observation remains available for deliberate inspection, but
the compact delta is the default decision evidence. The result is capped using
the existing changed-cell limit and serialized-size guard.

The prompt will require the model to update its hypothesis from this feedback,
distinguish frame change from objective progress, and stop querying the broker
after the target terminal state. An initial application snapshot suppresses
startup rereads. Candidate routes are described as upper bounds, not mandatory
routes.

### 2. Generic replay oracle and route optimizer

Add a small planning module with immutable planner records and a `TransitionOracle`
protocol. The optimizer accepts an already verified candidate sequence and an
oracle factory that creates a fresh deterministic replay environment. It tries
bounded candidate edits in increasing cost order:

1. delete one action;
2. delete pairs and triples when the configured search budget allows;
3. replace a local action with an allowed action or data variant supplied by the
   caller;
4. retain only candidates whose fresh replay reaches the requested terminal
   condition with matching identity and valid transition evidence.

The optimizer returns a shortest verified candidate found within its finite
budget. It does not call `ArcBroker.act`, mutate a live run, or infer success
from frame change alone. A caller may adapt sealed history or a real offline
engine to the oracle, but the optimizer itself imports neither `ArcBroker` nor
`ArcadeEngine`.

### 3. Exploration and replay modes

The live prompt will expose two generic modes:

- **Replay mode:** verify a supplied candidate one item at a time and stop at
  the terminal boundary.
- **Explore mode:** treat the candidate as an upper bound, use action feedback
  to seek a shorter route, and only publish a route after offline replay.

The mode is operator-selected and bounded. Existing normal solves retain replay
behavior unless exploration is explicitly requested.

### 4. Failure and compatibility behavior

- Oversized feedback is reduced to counts, digests, and `changed_cells_omitted`;
  it never becomes a tool failure after an action was committed.
- Missing, discontinuous, cross-level, or identity-mismatched history causes an
  optimizer candidate to be rejected before any claim of improvement.
- Terminal, reset, unavailable-action, and prediction-mismatch results preserve
  current broker semantics and action counts.
- Existing trace and replay schemas remain compatible; feedback is an additive
  private tool-result field.

## Alternatives considered

### Prompt-only guidance

Low implementation cost, but it cannot validate route edits and does not expose
the semantic deltas already available in history. It is insufficient for a
reproducible step-count improvement.

### Put search inside `ArcBroker`

Rejected because it mixes planning with the execution authority, complicates
action caps and replay evidence, and risks allowing speculative candidates to
mutate the live game.

### Put search inside `ArcadeEngine`

Rejected because the engine is a native SDK adapter and must remain unaware of
planning policy. It would also make generic tests depend on ARC SDK details.

## Verification criteria

- A changed and an unchanged fake transition produce bounded, accurate feedback.
- A fake deterministic oracle finds a shorter winning sequence by deletion and
  rejects a shorter sequence that does not reach the required terminal state.
- Optimizer inputs remain immutable and the optimizer never invokes a live
  broker action.
- Existing `act_checked` tests prove every batch item still increments the
  primitive action count independently.
- Prompt tests prove no game-specific ID, coordinates, or route literals are
  introduced into the generic prompt.
- Focused P7 tests and the repository test gate pass after implementation.
