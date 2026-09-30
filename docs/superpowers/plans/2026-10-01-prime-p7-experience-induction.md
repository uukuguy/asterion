# P7 Experience Induction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use inline execution in this session, task-by-task with TDD and a commit after each independently verified task.

**Goal:** Implement the 2026-10-01 experience-induction design so P7 extracts action effects, proposes mechanisms, verifies them through the simulator and replay gate, persists semantic experience, and evaluates reuse through pure P7 SP80 L1→L2→L3 runs.

**Architecture:** Keep `ArcHistoryRecord` as observed history evidence. Add a bounded induction layer that derives immutable `ActionEffect` records and `EffectHypothesis` candidates, then feeds only certificate-backed `MechanismSpec` models into the existing pure simulator/search path. Broker remains the sole action authority; Playbook persists semantic facts and candidate lifecycle separately from checked routes.

**Tech Stack:** Python 3.12, dataclasses, existing `unittest`, `WorldModelStore`, `MechanismSpec`, `ModelCertificate`, `model_search`, P7 bridge/operator, JSON Playbook persistence.

## Global Constraints

- Pure P7 runs must not receive offline exact routes, candidate action sequences, or route-adoption hints.
- Only `act_checked` may dispatch a checked probe or simulator plan.
- Mechanism candidates must be bounded JSON/declarative data; no code execution, filesystem, network, or process access.
- Confirmed facts require full current-history retrodiction plus a distinguishing real probe.
- Unknown or incomplete predictions must not become planner-eligible.
- Keyboard, click, and keyboard_click input surfaces use the same induction contracts.
- Cache and Playbook failures never block an otherwise valid exploratory action.
- Every task follows red test → minimal implementation → focused verification → commit.

## Task 1: ActionEffect and SimState contracts

**Files:**
- Create: `src/asterion/applications/prime/p7/experience_induction.py`
- Create: `tests/test_prime_p7_experience_induction.py`
- Modify: none

**Interfaces:**
- `extract_action_effect(previous: ArcHistoryRecord, record: ArcHistoryRecord) -> ActionEffect`
- `ActionEffect` exposes identity, level, sequence, action/data, frame/state digests, outcome, changed cells, and bounded component summaries.
- `SimState.from_observation(frame, level, state, available_actions, entities) -> SimState`
- `SimState` is immutable and carries unknown fields explicitly; it never calls an engine.

- [ ] Write failing tests for keyboard, click, keyboard_click data normalization, no-effect, level transition, connected changed-cell components, and immutable SimState construction.
- [ ] Run `uv run python -m unittest -v tests.test_prime_p7_experience_induction`; expect missing module/API failures.
- [ ] Implement strict bounded dataclasses and deterministic component extraction from the existing `stable_changed_cells` evidence.
- [ ] Re-run the focused tests and `git diff --check`.
- [ ] Commit: `p7: add action effect and simulator state contracts`.

## Task 2: Candidate induction and probe ranking

**Files:**
- Modify: `src/asterion/applications/prime/p7/experience_induction.py`
- Modify: `tests/test_prime_p7_experience_induction.py`

**Interfaces:**
- `EffectHypothesis` carries identity, level, candidate kind, normalized signature, supporting effect sequence numbers, lifecycle status, and optional declarative mechanism mapping.
- `ExperienceInducer.observe(effect: ActionEffect) -> tuple[EffectHypothesis, ...]`
- `ExperienceInducer.probe_plan(current: SimState, candidates: Sequence[EffectHypothesis]) -> ProbePlan`
- `ProbePlan` returns `ready`, `no-discriminating-probe`, or `unknown` and never dispatches actions.

- [ ] Add red tests showing two consistent effects create one bounded candidate, contradictory effects create a conflict/retired candidate, repeated no-effect actions do not create a planner candidate, and probe ranking rejects stale coordinates.
- [ ] Run the tests and verify the expected failures.
- [ ] Implement normalized signatures for cell edits, component translation, state/level transitions, and no-effect boundaries; require two consistent observations except for a low-confidence terminal candidate.
- [ ] Implement bounded information-gain ranking over current action whitelist and current-frame component centers.
- [ ] Re-run focused tests and commit: `p7: infer bounded action effect hypotheses`.

## Task 3: Declarative simulator compilation and certificate separation

**Files:**
- Modify: `src/asterion/applications/prime/p7/mechanism_model.py`
- Modify: `src/asterion/applications/prime/p7/model_search.py`
- Create: `tests/test_prime_p7_experience_simulator.py`

**Interfaces:**
- `compile_effect_hypothesis(hypothesis: EffectHypothesis) -> MechanismSpec | None`
- `simulate_step(spec: MechanismSpec, sim_state: SimState, action: object) -> SimPrediction`
- `SimPrediction` distinguishes `predicted`, `unknown`, and `conflict`, includes changed-cell evidence and rule provenance.
- `model_search` accepts only a current-prefix `ModelCertificate` and complete `SimState` inputs.

- [ ] Add red tests for relative component/cell edits, unknown hidden state, ambiguous rules, stale certificates, and model search returning complete per-step witnesses without dispatching.
- [ ] Run the new simulator tests and confirm they fail before implementation.
- [ ] Implement only the safe declarative subset; leave unsupported inventory/timer/object lifecycle effects as `unknown`.
- [ ] Separate observed transcript coverage from generalized model certificate metadata and reject certificates whose current prefix or world revision differs.
- [ ] Run simulator, native broker, and model-search focused tests; commit: `p7: compile verified mechanisms into bounded simulator`.

## Task 4: Broker induction lifecycle and automatic probe suggestion

**Files:**
- Modify: `src/asterion/applications/prime/p7/broker.py`
- Modify: `tests/test_prime_p7_native_broker.py`

**Interfaces:**
- Broker owns bounded `ActionEffect` history, `ExperienceInducer`, candidate lifecycle, and simulator coverage diagnostics.
- Add read-only broker methods: `action_effects()`, `mechanism_candidates()`, `probe_plan()`.
- `_record_world_evidence` extracts effects and updates candidates after each settled transition; it never dispatches automatically.
- A chosen probe enters the existing one-pending-probe and `act_checked` path.

- [ ] Add red broker tests proving effects/candidates are created after action transitions, no candidate dispatch occurs, and a matching probe can promote a mechanism while a mismatch retires it.
- [ ] Run the focused broker tests and observe expected failures.
- [ ] Integrate induction after history/world evidence recording, with bounded persistence failure handling and conflict invalidation.
- [ ] Ensure ordinary exploration remains available when no probe plan or simulator model exists.
- [ ] Run all native broker tests and commit: `p7: integrate experience induction with broker`.

## Task 5: Playbook persistence, rehydration, and public P7 tools

**Files:**
- Modify: `src/asterion/applications/prime/p7/playbook.py`
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Modify: `src/asterion/applications/prime/p7/live.py`
- Modify: `src/asterion/applications/prime/p7/ipython_host.py`
- Modify: generated P7 application tool resource if required by the build
- Modify: `tests/test_prime_p7_live_command.py`, `tests/test_prime_p7_bridge_dispatch.py`

**Interfaces:**
- Playbook stores bounded effect summaries, candidate status, model revision/certificate summaries, and conflict evidence separately from checked routes.
- Add read-only tools: `p7_action_effects`, `p7_mechanism_candidates`, `p7_probe_plan`, `p7_simulator_status`.
- Loaded advisory candidates are stale until current-level evidence reactivates them; confirmed mechanisms require current-prefix replay before planner use.

- [ ] Add red bridge/operator tests for registration, typed parameters, redacted bounded projections, identity mismatch, stale candidate rehydration, and no route injection.
- [ ] Implement Playbook schema extension and safe migration for old snapshots.
- [ ] Register tools through the existing application-level registry and generated worker facade, keeping tool IDs and schemas synchronized.
- [ ] Add prompt guidance that reads effect/candidate/simulator status before long deliberation but does not inject exact routes.
- [ ] Run bridge/live focused tests, lint, docs-check, and commit: `p7: persist and expose semantic game experience`.

## Task 6: Pure/integration boundary and digest correctness

**Files:**
- Modify: `src/asterion/applications/prime/p7/verified_history.py`
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Modify: `src/asterion/applications/prime/p7/broker.py`
- Modify: `tests/test_prime_p7_native_broker.py`, `tests/test_prime_p7_live_command.py`

- [ ] Add red tests for frame/state digest mix-ups, incomplete expectations, stale route provenance, and explicit success classification.
- [ ] Implement typed frame/state witness handling, fail-closed incomplete plan expectations, current-prefix certificate checks, and no action-only adoption.
- [ ] Preserve ordinary single-step exploration and probe dispatch; only checked mismatches stop batches.
- [ ] Run the complete focused P7 suite and commit: `p7: harden simulator and route evidence boundaries`.

## Task 7: Synthetic end-to-end learning evaluation

**Files:**
- Create: `tests/test_prime_p7_experience_learning.py`
- Modify: existing focused test modules only when a regression requires it

- [ ] Build a deterministic synthetic engine with keyboard, click, and mixed action surfaces, a repeatable object movement rule, a level transition, and one contradictory probe.
- [ ] Verify the full path: observe → ActionEffect → candidate → probe plan → `act_checked` → retrodiction → certificate → simulator search → checked plan → Playbook reload.
- [ ] Verify unknown hidden state bypasses the simulator without blocking ordinary exploration.
- [ ] Verify the reloaded model is stale until the new prefix is checked and then becomes planner-eligible.
- [ ] Run the synthetic end-to-end test and commit: `test: verify p7 semantic learning loop`.

## Task 8: Pure P7 SP80 L1→L2→L3 evaluation and repair loop

**Files:**
- Modify only code/tests/docs required by observed generic defects.
- Append results to `docs/status/JOURNAL.md` and update `docs/status/RESUME-NEXT-SESSION.md`.

- [ ] Rebuild the installed P7 wheel after Tasks 1–7.
- [ ] Run pure P7 SP80 L1 with offline optimization disabled; record current-level actions, effect count, candidate count, probe count, confirmed facts, simulator status, and worker cells.
- [ ] Re-run or advance to SP80 L2, then L3, always reporting current-level actions separately from replayed prefix actions.
- [ ] Stop after three consecutive failures or any generic mechanism defect; add a regression test and repair before continuing.
- [ ] Only claim “game experience reuse” if a confirmed semantic fact or certificate is loaded and demonstrably changes the next-level exploration/search path; a saved route alone does not count.
- [ ] Run focused tests, `make lint`, `make docs-check`, and `git diff --check` after every repair; commit each generic repair separately.

## Final verification

- `uv run python -m unittest -q tests.test_prime_p7_experience_induction tests.test_prime_p7_experience_simulator tests.test_prime_p7_experience_learning tests.test_prime_p7_native_broker tests.test_prime_p7_live_command tests.test_prime_p7_bridge_dispatch tests.test_prime_p7_model_search`
- `make lint`
- `make docs-check`
- `git diff --check`
- Pure P7 evidence for SP80 L1→L2→L3 with no offline route injection.
