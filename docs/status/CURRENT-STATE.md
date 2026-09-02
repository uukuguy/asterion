# Current State

## Project Snapshot

- Project: Asterion
- Active branch: local `main` at the verified integration head; `origin/main`
  remains unchanged
- Theme-level focus: Prime RLM-harness capability program: persistent IPython,
  recursive RLM, Continual Harness, and staged end-to-end evidence through ARC
- Project route: managed
- Canonical worklist:
  `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`
- Active work package: the approved Prime capability program replaces the
  proposed Smoke Full roadmap. Phase 3.2 Native Verified-loop remains
  External-limited at its exact idle barrier. Prime implementation begins only
  after the capability-program specification is reviewed and an external
  restricted-worker/sandbox profile is selected.
- Git recovery closure: one clean local `main` branch and one primary worktree
  remain. A verified complete-history bundle preserves every audited committed
  head, and separate patches/archive preserve accepted uncommitted source
  state. `origin/main` remains unchanged.

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
- Climb cycles 35 through 38 each occur exactly once:
  `check.client-interfaces-closure`, `check.operational-parity-closure`,
  `prime-system-parity-operation-host-callback`, and
  `check.native-controller-core-provider-free`.
  `next_action` is `phase-3.2-native-small-verification-sidecar`.
- `interfaces.operations` is PASS at exactly 15/15 Prime Gateway rows after
  H-035 plus H-036.
- Prime Gateway canonical `Verified-system-parity` remains PASS at H-037: the
  exact checker reports 61 passed, zero ledger blockers, and two excluded rows
  with zero provider/application operations.
- Native controller core is PASS at H-038. The exact provider-free receipt
  reports 10 common scenarios, five differential cases, eight crash points, all
  six prohibited operation counters at zero, and `promoted_feature_ids=[]`.
  Every one of the 61 compound `asterion.native` parity rows remains Missing.
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
  frames, cleanup, and zero Prime effects. Task 6's repository,
  cross-language, promotion, distribution, and independent review gates pass.
- H-038 passed canonical execution exactly once after clean pre-H gates:
  focused Native target, exact verifier, `make check`, `make promotion-check`,
  and `git diff --check`. Canonical state routes to
  `phase-3.2-native-verified-loop-design`; no compound Native row was promoted.
- Phase 3.2 provider-free receipt evidences nine Native Verified-loop rows
  with zero external counters. A parameter-free operator-owned host reads the
  existing `.env` configuration. Its second bounded run passed Gateway
  descriptor validation, lifecycle acceptance, and the checkpoint manager.
  Its current exact boundary is the manager idle barrier before the main RLM
  probe; the two bounded rows remain
  `External-limited`. Native `Verified-loop` and all compound Native rows
  remain Missing.
- Prime Smoke Core is closed: the real `make prime-smoke-core` receipt is
  PASS with one completed terminal and proves generated-program admission,
  depth policy, two-child work, causal messaging, active reconnect,
  application/oracle, healthy observations, budget, cleanup, and public
  privacy. This evidence is not Smoke Full or parity promotion evidence.

## Open Problems

- Keep every compound Asterion-native row missing until Phase 3.2+ evidence
  proves the exact mandatory scenarios.
- Prove pinned/next-build compatibility only with separate exact locks and
  reviewed difference records.
- Establish the restricted-worker/sandbox boundary and seven exact Prime
  capability acceptance products without widening the closed Smoke Core claim.

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
- `docs/superpowers/specs/2026-08-30-asterion-native-controller-core-design.md`
- `docs/superpowers/plans/2026-08-30-asterion-native-controller-core.md`
- `docs/superpowers/plans/2026-09-02-prime-smoke-core.md`
- `docs/superpowers/specs/2026-09-02-prime-smoke-core-full-research.md`
- `docs/superpowers/specs/2026-09-02-asterion-prime-capability-program-design.md`
- `docs/status/PRIME-PARITY-LEDGER.md`
- `docs/status/PRIME-TYPICAL-APPLICATIONS.md`
- `.superpowers/sdd/client-interfaces-task-10-report.md`
- `.superpowers/sdd/operational-parity-task-16-report.md`
- `.superpowers/sdd/native-core-task-10-report.md`

### Implementation entry points

- `src/asterion/control/providers/prime/ecosystem_parity_testing.py` — exact
  reduction from four ecosystem receipts to ten observations
- `src/asterion/control/providers/prime/parity_testing.py` — provider scenario
  registry
- `packages/typescript/prime-gateway/` — Prime daemon translation and durable
  private bridge
- `tools/check_prime_parity.py` — exact domain and system claim reducer
- `tools/verify_native_controller_core.py` — exact provider-free Native
  controller-core receipt verifier
- `tools/check_promotion.py` — isolated source/wheel/promotion verification

## Resume Instructions

1. Read this snapshot, `RESUME-NEXT-SESSION.md`, and the generated Climb tree.
2. Inspect `git status --short` and recent commits before staging anything.
3. Preserve unrelated dirty work and use exact partial staging.
4. Resume Phase 3.2 by injecting and reviewing an operator-owned small-
   verification host; otherwise retain the provider-free receipt unchanged.
5. Keep credentials, private configuration, and execution authority external.
6. Never promote provider-free or External-limited evidence to a broader PASS.
