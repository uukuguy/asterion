# Current State

Updated 2026-09-29. This file is the structural snapshot; session handoff and next actions are in `RESUME-NEXT-SESSION.md`.

## Project Snapshot

- Project: Asterion composable multi-runtime agent framework
- Current branch: `main`
- Theme-level focus: raising the BP35 official level score to the 115 cap under the operator-selected P7 model
- Project route: managed
- Canonical worklist: `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`
- Active work package: none

## Current Architecture

- Python owns orchestration, composition, application assembly, and execution.
- TypeScript validates shared contracts and packages Pi application resources.
- Rust owns controlled command execution.
- P7 is an application-level native ARC-AGI-3 solving route using an operator-injected Pi host and an operator-selected provider/model pair.
- `ASTERION_PRIME_PROVIDER` / `ASTERION_PRIME_MODEL` are read once in `p7/model_selection.py`; the trace identity, receipt, prefix reuse and runtime options all follow that selection.
- Framework runtime modules remain domain-neutral; application bridges own P7 tools and state observations.

## Open Problems

- No current P7 gameplay result is authorized or in flight.
- No P7 run has been executed with a non-default model; only the `openai-codex / gpt-6-sol` default has live evidence, and only as trace identity (no game action).
- The P7 level-witness path currently produces no game actions: the Pi model host restarts every ~15-25 s after starting. Observed 2026-09-29; cause undiagnosed.
- Full-game P7 capability remains unverified beyond the historical evidence retained before the GPT-6-Sol migration.
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
4. Treat `d50897f7` as the P7 gameplay baseline; `e392577` adds operator-selected P7 model configuration on top of it.
