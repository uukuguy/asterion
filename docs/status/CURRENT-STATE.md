# Current State

## Project Snapshot

- Project: Asterion composable multi-runtime agent framework
- Current branch: `main`
- Theme-level focus: native P7 builds persistent game knowledge and verifies whether it improves solving
- Project route: managed
- Canonical worklist: `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`
- Active work package: P7 experience induction, game-wide mechanisms, and bounded counterfactual planning

## Current Architecture

- Python owns P7 orchestration, broker authority, persistence, and operator assembly.
- `ArcBroker` validates identity, current history, action witnesses, and planner certificates before checked execution.
- `WorldModelStore` holds per-run mechanics/entities/relations and level-local visual evidence.
- `GameCognitionStore` remains an advisory progress cache; `SemanticCognitionStore` is the primary exact-game/L1 language cognition contract with atomic persistence and execution_authority=none.
- `ObservationState` provides one immutable representation for frame, input surface, HUD, timers, resources, entities, relations, and events.
- `GameMechanicsStore` persists game-wide mechanism candidates, conditions, effects, scope, evidence, and conflicts with `execution_authority=none`.
- `CognitionSession` runs bounded hypothesis/experiment/analyze/RESET episodes; `hypothesis_simulator.search_counterfactual` compares confirmed and hypothesis branches and never dispatches actions.
- `MechanismSpec`/`ModelCertificate`/`model_search` remain the only path from retrodicted local evidence to a checked executable plan.
- P7 application tools are registered through the Operator, worker bridge, live RPC module, and prompt; offline route injection is disabled for capability runs.

## Open Problems

- Native ARC history still records frame/state/level as the authoritative replay evidence; richer metadata needs an adapter that preserves protocol compatibility.
- Game-wide mechanisms are persisted and advisory, but cross-level confirmation and current-context binding still require live evidence.
- Counterfactual simulation is implemented and tested synthetically; its effect on real SP80 exploration and action efficiency is unverified.
- A pure P7 SP80 L1→L2→L3 run has not yet completed; prior L1 prefixes may be replayed evidence rather than fresh solving.
- Completion requires a cold-start versus warm-start comparison with confirmed model, simulator use, and current-level action counts.
- `tu93` L1 cognition has persisted three bootstrap hypotheses plus six LLM hypotheses across runs; the latest real run was externally cancelled before any action, so cognition-to-action effectiveness remains External-limited.

## Key Files

### Loaded every session

- `AGENTS.md`
- `MEMORY.md`

### State / handoff

- `docs/status/RESUME-NEXT-SESSION.md` — final session baton
- `docs/status/JOURNAL.md` — append-only event log
- `docs/status/INDEX.md` — status-file index

### P7 implementation entry points

- `src/asterion/applications/prime/p7/broker.py` — identity, evidence, execution, and learning integration
- `src/asterion/applications/prime/p7/observation_state.py` — immutable unified observations
- `src/asterion/applications/prime/p7/world_model.py` — per-run WorldMap facts and conflicts
- `src/asterion/applications/prime/p7/semantic_cognition.py` — persistent language-level cognition ledger
- `src/asterion/applications/prime/p7/cognition_session.py` — experiment episode state machine and event audit
- `src/asterion/applications/prime/p7/game_mechanics.py` — persistent game-wide mechanism memory
- `src/asterion/applications/prime/p7/hypothesis_simulator.py` — bounded counterfactual branches and subgoals
- `src/asterion/applications/prime/p7/mechanism_model.py` — declarative transitions and certificates
- `src/asterion/applications/prime/p7/model_search.py` — certificate-gated bounded search
- `src/asterion/applications/prime/p7/operator.py` — P7 tools and host wiring
- `src/asterion/applications/prime/p7/live.py` — live RPC and worker plumbing

## Execution and evidence boundary

- Input-type priors and exact-game memory are advisory; persistence failures do not block ordinary exploration.
- Checked actions require current identity, prefix, frame/state/level expectations, and certificate context.
- Hypothesis simulation, offline optimization, and Playbook records never grant execution authority by themselves.
- Cognition experiments now keep generic `frame_changed` observations undetermined; semantic claims require a concrete predicted frame, or a constrained level/state predicate. Checked-action experiment mismatches are recoverable in cognition mode.
- A passing synthetic induction test does not establish real-game capability; live claims require sealed trace, replay verification, and explicit diagnostics.

## Resume Instructions

1. Read this file and `docs/status/RESUME-NEXT-SESSION.md`.
2. Read the latest `JOURNAL.md` entries and `AGENTS.md`.
3. Run `git status --short` and `git log --oneline -5`.
4. Run `make lint`, `make docs-check`, and the focused P7 regression suite before any live game attempt.
5. If live work resumes, keep offline optimization disabled and report current-level steps separately from replay prefixes and total primitive actions.
