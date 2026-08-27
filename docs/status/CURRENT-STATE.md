# Current State

## Project Snapshot

- Project: Asterion
- Active branch: `h024-ecosystem-capabilities`
- Theme-level focus: Prime system parity through closed, exact evidence
  packages, followed by Asterion-native kernel parity
- Project route: managed
- Canonical worklist:
  `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`
- Active work package: Phase 2 — H-035 client-interface design review

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

- Prime Gateway `ecosystem.capabilities` is PASS at 10/10 provider-free:
  resources, extensions, packages, and MCP evidence reduce to ten immutable
  evidence rows with zero provider/model operations.
- The exact H-034 cycle passed at `ef685f4`: four ecosystem gates, exact 10/10
  reduction, `make check`, isolated `make promotion-check`, and
  `git diff --check` all passed.
- `make check` passed 1,954 Python tests plus TypeScript, Ruff, docs, Rust
  test/fmt/clippy, sdist, and wheel.
- Promotion reported `promotion full PASS commands=27 provider_operations=0
  full_dataset=no`.
- Climb cycle 34 occurs exactly once. H-034 is passed and H-035 is pending.
- Every Asterion-native ecosystem row remains `missing`.
- `Verified-system-parity` remains `BLOCKED` on `interfaces.operations`;
  ecosystem evidence does not imply client, operational, system, or native
  parity.
- The native RLM check remains `External-limited`; no provider operation ran in
  the H-034 verification.
- H-035 inventory identified the exact nine interface features and four
  provider-free evidence packages. The design is committed at `7add4fb` and is
  awaiting specification review; no client implementation exists yet.

## Open Problems

- Review
  `docs/superpowers/specs/2026-08-28-asterion-prime-client-interfaces-design.md`.
  After approval, write the detailed implementation plan before changing code.
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
- `docs/superpowers/specs/2026-08-28-asterion-prime-client-interfaces-design.md`
- `docs/status/PRIME-PARITY-LEDGER.md`
- `.superpowers/sdd/ecosystem-task-10-report.md`

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
4. Do not implement client code until the design specification is reviewed.
5. Keep credentials, private configuration, and execution authority external.
6. Never promote provider-free or External-limited evidence to a broader PASS.
