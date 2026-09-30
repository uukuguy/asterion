# Current State

Updated 2026-09-30. This file is the structural snapshot; session handoff and next actions are in `RESUME-NEXT-SESSION.md`.

## Project Snapshot

- Project: Asterion composable multi-runtime agent framework
- Current branch: `main`
- Theme-level focus: raising the BP35 official level score to the 115 cap under the operator-selected P7 model
- Project route: managed
- Canonical worklist: `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`
- Active work package: P7 same-game world model and replay-gated route adoption; implementation complete, repository gate pending.

## Current Architecture

- Python owns orchestration, composition, application assembly, and execution.
- TypeScript validates shared contracts and packages Pi application resources.
- Rust owns controlled command execution.
- P7 is an application-level native ARC-AGI-3 solving route using an operator-injected Pi host and an operator-selected provider/model pair.
- `ASTERION_PRIME_PROVIDER` / `ASTERION_PRIME_MODEL` are read once in `p7/model_selection.py`; the trace identity, receipt, prefix reuse and runtime options all follow that selection.
- Framework runtime modules remain domain-neutral; application bridges own P7 tools and state observations.

## Open Problems

- The same-game WorldModel, TransitionModel, Playbook, declarative mechanism certificates, P7 application tool registry, and replay expectation gate are implemented and covered by focused tests.
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
- `src/asterion/applications/prime/p7/model_selection.py` — the only reader of the P7 model selection
- `src/asterion/applications/prime/p7/live.py` — Pi RPC live execution plumbing
- `src/asterion/applications/prime/runtime_binding.py` — fixed Prime runtime selection
- `Makefile` — provider-backed P7 presets

## Resume Instructions

1. Read this file and `RESUME-NEXT-SESSION.md`.
2. Read the latest `JOURNAL.md` entries and `AGENTS.md`.
3. Run `git status --short` and `git log --oneline -5`.
4. Rerun the repository gate before any live game attempt; then use the P7 implementation boundary for a controlled live verification.
