# Current State

## Project Snapshot

- Project: Asterion
- Active branch: `recovery/pre-consolidation-root-20260830`
- Theme-level focus: Prime system parity through closed, exact evidence
  packages, followed by Asterion-native kernel parity
- Project route: managed
- Canonical worklist:
  `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`
- Active work package: Phase 2 production closure — callback Tasks 1 through 6
  are independently approved through `9c00a9a`; Task 7's dormant H-037 gate is
  committed at `610c39f`, passed detached full verification, and now owns the
  single canonical closure transition.

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
- H-036 is PASS exactly once: its six provider-free operational receipts cover
  `operation.auth`, `operation.model-selection`,
  `operation.settings-keybindings`, `operation.telemetry-usage`,
  `operation.doctor`, and `operation.controlled-update-restart` (6/6
  selected/passed, zero blocking) with zero provider/application operations.
- The clean canonical H-036 closure used the pinned Prime source at
  `a18809e00ea30638584d87b3afea7285a9d7296c`, rebuilt locked workspaces under
  Node 22.23.2, then passed `make check`, `make promotion-check`, and
  `git diff --check`. Promotion reported `commands=28`, zero provider
  operations, and `full_dataset=no`.
- Climb cycle 35 occurs exactly once with
  `check.client-interfaces-closure`; climb cycle 36 occurs exactly once with
  `check.operational-parity-closure`; `next_action` is `future-work-queue`.
- `interfaces.operations` is PASS at exactly 15/15 Prime Gateway rows after
  H-035 plus H-036.
- Native rows remain missing. The exact checker reports 61 passed, zero ledger
  blockers, and two excluded rows with zero provider/application operations.
  Root/child dispatcher composition and the real callback path now pass, but
  the canonical `Verified-system-parity` transition remains pending H-037.
- `OperationManager` now exposes immutable dispatcher identity, and the
  reviewed Python callback server accepts only exact identity-bound frames over
  a private `0600` Unix socket.
- The reviewed TypeScript callback client now issues one exact request per Unix
  connection with write-side EOF, strict response validation, no retries, and
  an absolute deadline. The sole production descriptor path assembles that
  client into `PrimeOperationGateway`.
- The reviewed Python factory now snapshots one exact injected dispatcher,
  supplies a fresh 256-bit callback descriptor, and shares one callback-first,
  process-then-callback managed transport across both Prime clients.
- Root and nested child sessions now bind distinct identity-exact managers to
  both provider context and `ControlHost`. The real Node sidecar proves
  execute, reconcile, cancel, missing-callback, failure/no-retry, body-free
  frames, cleanup, and zero Prime effects. Task 6's final 2335-test repository,
  cross-language, promotion, distribution, and independent review gates pass;
  Phase 2 now awaits only the single H-037 closure.
- The dormant H-037 gate passed detached verification with 2338/2338 Python
  tests, TypeScript and Rust checks, package builds, and the 28-command
  promotion gate. Its isolated Climb state recorded H-037 exactly once and
  routed to `phase-3-native-kernel-design`; canonical state remains at H-036.

## Open Problems

- Option 1A and its root/child correction are verified: each session keeps one
  Python `OperationManager`, while Prime owns only a lifecycle-managed private
  callback transport.
- Execute the independently verified H-037 gate exactly once on canonical
  state; do not broaden its provider-free command identity or promote native
  rows.
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
- `docs/superpowers/plans/2026-08-10-asterion-prime-operational-parity.md`
- `docs/superpowers/specs/2026-08-28-asterion-prime-client-interfaces-design.md`
- `docs/superpowers/specs/2026-08-30-prime-operation-host-callback-design.md`
- `docs/superpowers/plans/2026-08-30-prime-operation-host-callback.md`
- `docs/status/PRIME-PARITY-LEDGER.md`
- `.superpowers/sdd/client-interfaces-task-10-report.md`
- `.superpowers/sdd/operational-parity-task-16-report.md`

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
4. Continue the approved callback plan at Task 7 by executing the detached-
   verified H-037 gate exactly once on canonical state.
5. Keep credentials, private configuration, and execution authority external.
6. Never promote provider-free or External-limited evidence to a broader PASS.
