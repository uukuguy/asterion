# Current State

Updated 2026-10-01. This file is the structural snapshot; session handoff and next actions are in `RESUME-NEXT-SESSION.md`.

## Project Snapshot

- Project: Asterion composable multi-runtime agent framework
- Current branch: `main`
- Theme-level focus: make native P7 accumulate type cognition, exact-game experience, and a verified same-game world model instead of restarting visual exploration on every level
- Project route: managed
- Canonical worklist: `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`
- Active work package: P7 same-game world model, retrodicted declarative simulator, and bounded model search; implementation is in place, live capability remains unverified.

## Current Architecture

- Python owns orchestration, composition, application assembly, and execution.
- TypeScript validates shared contracts and packages Pi application resources.
- Rust owns controlled command execution.
- P7 is an application-level native ARC-AGI-3 solving route using an operator-injected Pi host and an operator-selected provider/model pair.
- `ASTERION_PRIME_PROVIDER` / `ASTERION_PRIME_MODEL` are read once in `p7/model_selection.py`; the trace identity, receipt, prefix reuse and runtime options all follow that selection.
- Framework runtime modules remain domain-neutral; application bridges own P7 tools and state observations.

## Open Problems

- `WorldModelStore` persists mechanics/entities/relations and level-local visual hypotheses. `MechanismSpec` plus `ModelCertificate` now provide a safe executable model only after complete current-history retrodiction; `p7_model_search` exposes bounded BFS/A* plans with checked frame/state expectations. Design and limits are documented in `docs/architecture/prime-p7-world-model-simulator.md`.
- The model-search path is covered by synthetic mechanism tests and P7 bridge regressions. No live game run has yet proven that GPT-6.1-Sol can form a useful mechanism hypothesis, certify it, and complete a new level without a route hint.
- A controlled TU93 L1 witness was run after the replay-gated route changes, then operator-cancelled at 18 current-level actions with zero completed levels; it is external-cancel evidence only, not a verified result. Focused tests do not prove improved game-solving capability.
- Explicit level-witness runs now use the selected level's human baseline sum as their action cap; the old non-full-solve fallback of 500 remains only on the unmodified selection object and is no longer used by the witness entry point.
- The full repository gate completed 3509 tests with one promotion-environment failure because an offline npm-ci test observed one network request; `make lint`, `make docs-check`, Pyright on changed model modules, and the combined 223-test P7 suite passed.
- Generated `.asterion-private` evidence may contain stale post-baseline runs and must not be treated as current source state.

## Key Files

### Loaded every session

- `AGENTS.md`
- `MEMORY.md`

### State / handoff

- `docs/status/RESUME-NEXT-SESSION.md` — current session baton
- `docs/status/JOURNAL.md` — append-only event log
- `docs/status/INDEX.md` — status-file index

### Implementation entry points

- `src/asterion/applications/prime/p7/operator.py` — P7 operator and host wiring
- `src/asterion/applications/prime/p7/model_search.py` — certificate-gated bounded simulator search
- `src/asterion/applications/prime/p7/mechanism_model.py` — safe declarative transition model and certificate
- `src/asterion/applications/prime/p7/model_selection.py` — the only reader of the P7 model selection
- `src/asterion/applications/prime/p7/cognition.py` — bounded persistent type priors and exact-game experience
- `src/asterion/applications/prime/p7/live.py` — Pi RPC live execution plumbing
- `src/asterion/applications/prime/runtime_binding.py` — fixed Prime runtime selection
- `Makefile` — provider-backed P7 presets

## Cognition and execution boundary

- `GameCognitionStore` persists input-type profiles and exact-game progress under `.asterion-private/prime-p7-live/cognition.json` and exposes them through `p7_cognition()` / `p7_client.cognition()`.
- Type profiles are `prior-only`; exact-game memory is advisory until the current prefix and evidence are checked. Cache writes never gate normal exploration.
- Execution authority is narrow: only identity or checked-witness mismatches stop a batch. Ordinary probes, single-step exploration, and certified model search remain available. See `docs/architecture/prime-p7-cognition-and-experience.md`.

## Resume Instructions

1. Read this file and `RESUME-NEXT-SESSION.md`.
2. Read the latest `JOURNAL.md` entries and `AGENTS.md`.
3. Run `git status --short` and `git log --oneline -5`.
4. Rerun the repository gate before any live game attempt; then use the P7 implementation boundary for a controlled live verification.
