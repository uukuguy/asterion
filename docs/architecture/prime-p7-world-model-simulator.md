# P7 World Model and Verified Simulator

Updated 2026-10-01.

## Finding from the implementation audit

The original WorldMap implementation was a useful evidence store, but it was
not yet a game model. `WorldModelStore` retained mechanics, entities,
relations, hypotheses, and level memory. `TransitionModel` validated the
observed history chain. Neither component could predict an unseen successor,
compare candidate futures, or decide whether a long route was safe to execute.
The model therefore still depended on the LLM repeating visual exploration on
each level.

The new boundary is explicit:

```text
frame/action history
        │
        ├─ visual hypotheses (advisory, level-local)
        ├─ confirmed facts (persistent same-game playbook)
        └─ declarative MechanismSpec
                    │
            full-history retrodiction
                    │
             ModelCertificate
                    │
             bounded model search
                    │
          checked plan → act_checked
```

Only a certificate-backed mechanism reaches the planner. A model result is an
offline plan, never an implicit action dispatch. `act_checked` remains the
single authority that can spend an action slot and stops at the first observed
divergence.

## Three memory layers

### Game-global cognition

`WorldModelStore.mechanics` holds confirmed executable mechanics. Confirmed
facts are persisted in the same-game Playbook and loaded into a new run only
when game id, seed, and level count match exactly. A loaded mechanism is still
replayed against the current run prefix before it becomes planner-eligible.

`entities` and `relations` hold stable, evidence-backed object knowledge. Visual
regularities remain hypotheses until an action changes a settled cell inside
the candidate bounds. This prevents a palette guess or a prior-level click
coordinate from becoming an authority.

### Level-local map

When the broker advances a level, level-local entities, relations, and visual
hypotheses are refreshed from the new settled frame. Confirmed mechanics remain
available. This matches how a human carries control knowledge into a new room
while rebuilding the room layout.

### Route memory

The Playbook stores checked routes with exact action data and frame/state
expectations. A route can be replayed only when its identity and every witness
match. Route memory is evidence and a warm start; it is not a substitute for
current-level perception or a model certificate.

## Simulator contract

`MechanismSpec.predict` is a safe declarative transition function. It accepts a
settled frame, level, state, action, and confirmed entity values and returns a
predicted frame/level/state or `unknown`/`conflict`. It has no model-code
execution, filesystem, network, or process access. Current effects are bounded
cell edits, exact selected-cell translation, component-pattern translation,
state updates, and level updates. Component-pattern translation matches a
bounded source shape at the current frame, requires the observed number of
matches and clear destination cells, and fails closed when the shape is
ambiguous or out of bounds.

`model_search.search_model` performs a bounded BFS or A* search over those
predictions. Its action set is focused and evidence-backed:

* currently available non-click actions;
* previously observed action/data pairs;
* changed cells and centers of current visual components for `ACTION6`.

It never enumerates the full click grid. Unknown or conflicting rules are
skipped. `GAME_OVER` states are pruned. Search has node and depth caps and
returns one of `found`, `no-plan`, `budget-exhausted`, `model-unavailable`, or
`invalid-input`. A no-plan result means the current model/search budget is
insufficient; it does not prove that the puzzle has no solution.

Every returned action includes `frame_sha256`, `levels_completed`, and `state`
expectations. The worker must pass the action/expect dictionaries unchanged to
`p7_act_checked`; the broker verifies the real frame after every dispatch.

## Model lifecycle

1. **Acquire:** the model observes settled frames, action deltas, component
   candidates, and object relations.
2. **Hypothesize:** the model submits one canonical `MechanismSpec` and one
   distinguishing probe. The broker stores it as a hypothesis.
3. **Retrodict:** the probe and the complete current history must match the
   predicted frame, hashes, changed cells, level, and state.
4. **Certify:** a `ModelCertificate` records the model digest and contiguous
   history coverage. `retrodiction_status.planner.eligible` becomes true.
5. **Plan:** `p7_model_search()` searches only the certified model and returns
   a checked plan without dispatching.
6. **Execute:** P7 explicitly submits the plan to `p7_act_checked`. Any
   mismatch invalidates the route and records a conflict for replanning.
7. **Repair or bypass:** a contradiction clears the certificate. The model can
   submit a new probe, or P7 can bypass the incomplete model and use a fresh
   falsifiable action. The planner is advisory, so a failed search does not
   block ordinary exploration.

The public status now distinguishes observed history from planner authority:
`retrodiction_status.status` describes the history loop, while
`retrodiction_status.planner.status` is `absent`, `hypothesis`, `verified`, or
`stale` and includes only a model digest and certified record count.

## Tycho and Retrodict patterns adopted

Tycho's useful separation is an executable task model with state, transition,
rendering, outcome, optional focused actions, and a planner; it verifies the
model against observed transitions before planning and treats model use as an
active abstraction decision. This repository adopts the safe subset: a
declarative transition function, explicit certificate, focused candidate
actions, bounded search, and a planner bypass when the model is not useful.

Retrodict's useful loop is to log every frame, replay a hypothesis against
history before spending an action, attach exact expectations to each planned
step, stop at the first mismatch, and escalate to a simulator/search only when
the direct loop is stuck. P7 now has those same boundaries through the
Playbook, `MechanismSpec`, `ModelCertificate`, `model_search`, and
`act_checked`. A future extension can add an executable hidden-state model and
an escalation trigger; it must preserve the same replay gate.

References: [Tycho paper](https://arxiv.org/abs/2607.28287),
[Tycho implementation](https://github.com/NIMI-research/Tycho), and
[Retrodict implementation](https://github.com/ryanbbrown/Retrodict).

## Current limits

The declarative effect vocabulary does not yet infer arbitrary hidden
inventories, timers, or object lifecycles from pixels. Those must be expressed
as confirmed facts and supported by a matching mechanism rule. The planner
also does not claim optimality: it returns the first bounded BFS/A* route it
finds. Route compression and optimality proofs remain separate diagnostics.
These limits are deliberate; using an unverified or guessed simulator would
recreate the route-injection and false-success failures this design is meant to
remove.
