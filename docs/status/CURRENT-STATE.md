# Current State

## Project Snapshot

- Project: Asterion
- Current branch: `main`
- Theme-level focus: DCI capability parity and Asterion framework integrity
- Project route: direct
- Canonical worklist: three approved implementation plans under `docs/superpowers/plans/`
- Active work package: design and audit complete; implementation not started

## Current Architecture

- `src/asterion/cli.py` and product CLIs select an installed provider and exact application identity.
- Providers expose static assemblies resolved through deterministic package catalogs and composers.
- Python owns orchestration, assembly, runners, runtime adapters, and injected host-service protocols.
- TypeScript validates shared contracts and Node integration; Rust owns controlled process execution.
- DCI and controlled-code capabilities are bundled products above domain-neutral framework modules.

## Open Problems (theme-level)

- Runtime v1, composition, catalog immutability, and package evidence transport
  have verified fail-closed gaps.
- Installed acceptance counts packaged inventory but does not separately prove
  provider reachability or executable closure.
- Generic CLI runtime selection imports DCI configuration and is not hermetic
  against the repository `.env`.
- DCI paper-reference profiles currently mix paper, GitHub, and Asterion-safe
  semantics.
- Full reproduction authorization, budget enforcement, and RunManifest
  compilation do not yet form an executable loop.
- Provider-backed DCI verification remains bounded by external Pi, resources, and operator credentials.

## Key Files

### Loaded every Claude session
- `AGENTS.md`
- `CLAUDE.md`

### State / handoff
- `docs/status/RESUME-NEXT-SESSION.md` — current session handoff
- `docs/status/CURRENT-STATE.md` — this file
- `docs/architecture/dci-capability-audit.md` — approved capability mapping and
  gap register

### Approved implementation plans
- `docs/superpowers/plans/2026-07-24-asterion-protocol-composition-hardening.md`
- `docs/superpowers/plans/2026-07-24-asterion-application-authority.md`
- `docs/superpowers/plans/2026-07-24-dci-provenance-reproduction.md`

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
5. Execute the three approved plans in order; do not start provider-backed
   reproduction before the protocol and authority plans pass.
