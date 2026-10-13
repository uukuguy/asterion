# P7 Coverage Decision Implementation Plan

> For agentic workers: use the existing supervised subagent execution and independent source review. The user approved implementation and the subsequent bounded L9 trial.

**Goal:** Make incomplete prediction coverage change real action selection, retain counterexamples across model revision, and verify the result on the same isolated eight-level checkpoint.

**Architecture:** Keep the existing P7 Solver primitive loop and shared IPython RolloutRuntime. Domain coverage, explicit probing and historical model checks belong to P7; generic Prime remains domain-neutral. Reuse plan purpose/goal/assumptions, current observation and registration identity, existing plan results and private rollout evidence.

**Tech Stack:** Python unittest and persistent IPython; TypeScript application-tool description; generated wheel extension resources.

## Global constraints

- No hidden engine access, L9-specific rules or historical future-L9 evidence.
- Fatal and retained-risk stops, unavailable applicability, cancellation, observation/kernel changes, uncertain execution and budgets cannot be overridden by a probe.
- RESET retains its recovery-boundary behavior and invalidates model registration; it does not erase counterexamples.
- Unknown is neither fatal certainty nor safety. An explicit probe records an actor decision, not proof that its risk/cost estimate is true.
- Do not require extra LLM calls or NOTES writes for normally covered primitives.
- Run relevant boundary checks and independent changed-code review; no unrelated broad regression or paid trial before the repair is committed.

## Task 1: Explain gaps and stop default unknown execution

**Files:** `src/asterion/applications/prime/p7/rollout.py`, `rollout_runtime.py`, `solver.py`; relevant `tests/test_prime_p7_*rollout*.py`.

- [x] Write an actual standard-operator/shared-kernel regression: registered model returns unknown; an advance plan applies zero actions, stops as `model-coverage-review`, and returns the current observation plus missing coverage evidence.
- [x] Include a batch with a covered first step and unknown second step; only the first step is dispatched, and the stopped suffix remains unexecuted.
- [x] Run the new test to observe RED before implementation.
- [x] Preserve the existing rollout outcome/risk. Attach bounded gap information for the callback/component that stopped, the available microstep/action index, and its raw evidence reference. Object/view-boundary explanations supplied by an actor model remain model claims, not engine facts.
- [x] Add coverage review after the existing fatal/control/ref/generation checks and before real dispatch. RESET stays an explicit recovery exception under the existing hard boundaries.

Expected integration assertions:

```python
self.assertEqual(result['stop_reason'], 'model-coverage-review')
self.assertEqual(result['applied_count'], 0)
self.assertEqual(engine.calls, [])
```

## Task 2: Admit an explicit bounded probe after review

**Files:** `solver.py`, P7 prompt/tool description and their tests.

- [x] Add a failing test for a single-primitive probe matching an already returned coverage review at the exact observation, action, model registration and kernel generation.
- [x] Reuse `purpose='probe'`, a nonempty `goal`, and nonempty `risk:` / `cost:` entries in `assumptions`. Risk states the unknown consequence; cost records one charged action and possible death/replay costs, retaining unknown costs as unknown.
- [x] A probe without a matching review, after observation/model changes, or with multiple primitives must not bypass review.
- [x] Recompute prediction for every admitted probe; newly found fatal risk still blocks dispatch. Explicit probing cannot bypass old fatal evidence or uncertain execution.
- [x] Implement using recorded results in the existing Solver plan registry, with no new authorization token, external store or authority in manifests.

Probe request uses the existing plan contract:

```python
plan = {
    'plan_id': 'new-probe-id', 'start': current_reference,
    'purpose': 'probe', 'goal': 'Test the unsupported contact effect after review',
    'assumptions': ['risk: contact outcome is unknown and may be fatal',
                    'cost: one paid action; death and recovery cost remain unknown'],
    'steps': [{'action': candidate_action}],
}
```

## Task 3: Attach actual counterexamples to model revision

**Files:** `rollout_runtime.py`, `research_runtime.py`, existing feedback/rollout tests.

- [x] Persist deaths and verifiable prediction discrepancies using the existing evidence path, with exact pre/post observation, action, model revision and claim provenance.
- [x] Keep actor plan-expectation mismatches distinct from model-outcome contradictions. Do not compare arbitrary hidden/model JSON state to an actual board.
- [x] On a new registration, use the existing model/helper to re-evaluate relevant current-level/current-run cases without real actions or provider calls. Preserve explicit unknown, unresolved, failed and contradicted outcomes.
- [x] Re-registering unchanged functions, changing a model name or updating NOTES must not clear prior unresolved evidence.
- [x] Backtests remain local case evidence, not global dynamics certification; old identified fatal risks remain independently retained.

## Task 4: Review, package and run Task57

- [x] Update minimal P7 guidance and TypeScript description; synchronize all three generated extension resources.
- [x] Run targeted Python rollout, risk-scope, recovery and actual standard-entry tests; run `npm --prefix packages/typescript/asterion-prime-extension test`, resource consistency, lint and docs checks.
- [x] Independent source review checks every primitive, probe binding, case provenance, unknown/fatal priority and unchanged generic Prime boundaries.
- [ ] Commit/push code and core state before starting the authorized run.
- [ ] Reuse the already admitted Task55 prefix-only export: 335 actions/eight levels, NOTES301, no future-L9 history/frames/cells. Freeze repaired source/wheel; target9, 163 new actions/total498, model1024/tool4096, operator3600/guest3780 seconds.
- [ ] Monitor coverage reviews, explicit probes, model registration/backtests, fatal stops, actual mismatches and costs separately. Do not hint to the actor or replace the running wheel.
- [ ] Record the actual terminal reason, restoration/new actions, sealed/replay/cleanup status and inactive unit; publish the result without claiming a partial pass is nine-level completion.
