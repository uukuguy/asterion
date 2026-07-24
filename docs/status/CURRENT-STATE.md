# Current State

## Project Snapshot

- Project: Asterion
- Current branch: `main`
- Theme-level focus: standalone multi-runtime agent framework integrity
- Project route: direct
- Canonical worklist: none
- Active work package: none

## Current Architecture

- `src/asterion/cli.py` and product CLIs select an installed provider and exact application identity.
- Providers expose static assemblies resolved through deterministic package catalogs and composers.
- Python owns orchestration, assembly, runners, runtime adapters, and injected host-service protocols.
- TypeScript validates shared contracts and Node integration; Rust owns controlled process execution.
- DCI and controlled-code capabilities are bundled products above domain-neutral framework modules.

## Open Problems (theme-level)

- No active implementation objective is recorded after the standalone extraction work.
- Provider-backed DCI verification remains bounded by external Pi, resources, and operator credentials.

## Key Files

### Loaded every Claude session
- `AGENTS.md`
- `CLAUDE.md`

### State / handoff
- `docs/status/RESUME-NEXT-SESSION.md` — current session handoff
- `docs/status/CURRENT-STATE.md` — this file

### Implementation entry points
- `src/asterion/cli.py` — generic provider/application CLI
- `src/asterion/runtime/protocol.py` — public runtime protocol
- `src/asterion/packages/composition.py` — deterministic package composition
- `src/asterion/runner/application.py` — resolved application execution
- `src/asterion/applications/` — installed product providers and assemblies
- `schemas/` — canonical cross-language protocol schemas

## Resume Instructions

1. Read this file (structure / theme / open problems).
2. Read `RESUME-NEXT-SESSION.md` (in-flight intent + next concrete action).
3. Run `git status --short` and `git log --oneline -5`.
4. `AGENTS.md` and `CLAUDE.md` supply repository rules.
