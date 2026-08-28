# Current State

## Project Snapshot

- Project: Asterion
- Active branch: `feature/prime-client-interfaces`
- Theme-level focus: Prime system parity through closed, exact evidence
  packages, followed by Asterion-native kernel parity
- Project route: managed
- Canonical worklist:
  `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`
- Active work package: Phase 2 — H-036 operational surface inventory

## Current Architecture

- Asterion is a composable multi-runtime framework. DCI is a reference product;
  generic framework layers remain domain-neutral.
- Python owns orchestration, exact resolution, authority, admission, budgets,
  canonical journal/state, application execution, and public-safe evidence.
- TypeScript validates shared contracts and owns the Prime Node/Gateway
  boundary. Rust remains limited to controlled execution.
- Prime Gateway and the future native kernel are peer control providers over
  closed Asterion contracts; neither may authorize itself or bypass runners and
  injected host services.
- Provider-neutral ledgers keep implemented, provider-free, bounded-provider,
  system-parity, and native-parity claims distinct. Evidence promotes only the
  exact scenario and domain it proves.
- All client surfaces must consume one validated public event stream and one
  private-value service. They may not introduce alternate composers or runners.
- The approved design places a new closed `asterion.agent-client/v1`
  projection above `ControlHost`; existing control/runtime v1 contracts remain
  unchanged.
- Prime source, credentials, provider configuration, private content, and
  generated evidence remain external and operator-owned.

## Verified Boundary

- Prime Gateway `ecosystem.capabilities` remains PASS at 10/10 provider-free.
- H-035 is PASS exactly once: its four provider-free client receipts cover nine
  `interface.*` rows (9/9 selected/passed, zero blocking) with zero
  provider/model/credential/network/upload operations.
- The clean detached closure used the pinned Prime source at
  `a18809e00ea30638584d87b3afea7285a9d7296c`, rebuilt its locked workspaces
  under Node 22.23.2, then passed `make check`, `make promotion-check`, and
  `git diff --check`. Promotion reported `commands=27`, zero provider
  operations, and `full_dataset=no`.
- Climb cycle 35 occurs exactly once with
  `check.client-interfaces-closure`; H-036 is pending.
- Native rows and the six `operation.*` rows remain missing.
- `interfaces.operations` and `Verified-system-parity` remain BLOCKED. No
  client evidence promotes a broader system or native claim.

## Open Problems

- Design and verify six separate operational features after the client package:
  auth, model selection, settings/keybindings, telemetry/usage, doctor, and
  controlled update/restart.
- Keep every Asterion-native row missing until Phase 3 evidence exists.
- Prove pinned/next-build compatibility only with separate exact locks and
  reviewed difference records.

## Key Files

### Loaded every session

- `AGENTS.md`
- `docs/status/INDEX.md`
- `docs/status/RESUME-NEXT-SESSION.md`
- `docs/status/JOURNAL.md`
- `docs/status/DECISIONS.md`
- `docs/status/climb/research-tree.md`

### Canonical program and evidence

- `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`
- `docs/superpowers/plans/2026-08-10-asterion-prime-system-parity.md`
- `docs/superpowers/plans/2026-08-10-asterion-prime-ecosystem-parity.md`
- `docs/superpowers/plans/2026-08-10-asterion-prime-client-interfaces-parity.md`
- `docs/superpowers/specs/2026-08-28-asterion-prime-client-interfaces-design.md`
- `docs/status/PRIME-PARITY-LEDGER.md`
- `.superpowers/sdd/client-interfaces-task-10-report.md`

### Implementation entry points

- `src/asterion/control/providers/prime/ecosystem_parity_testing.py` — exact
  reduction from four ecosystem receipts to ten observations
- `src/asterion/control/providers/prime/parity_testing.py` — provider scenario
  registry
- `packages/typescript/prime-gateway/` — Prime daemon translation and durable
  private bridge
- `tools/check_prime_parity.py` — exact domain and system claim reducer
- `tools/check_promotion.py` — isolated source/wheel/promotion verification

## Resume Instructions

1. Read this snapshot, `RESUME-NEXT-SESSION.md`, and the generated Climb tree.
2. Inspect `git status --short` and recent commits before staging anything.
3. Preserve unrelated dirty work and use exact partial staging.
4. Start H-036 only after its own approved plan and evidence boundary exist.
5. Keep credentials, private configuration, and execution authority external.
6. Never promote provider-free or External-limited evidence to a broader PASS.
