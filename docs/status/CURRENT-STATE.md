# Current State

## Project Snapshot

- Project: Asterion
- Active branch: local `main`; implementation verification is scoped to its
  named boundaries, and `origin/main` remains unchanged
- Theme-level focus: close the existing seven Prime end-to-end capability
  scenarios; Prime and Native remain parallel runtimes within the unified
  capability-package framework
- Project route: managed
- Canonical worklist: `docs/status/PRIME-TYPICAL-APPLICATIONS.md`
- Active work package: P1 through P4 development reproductions and exact-selector
  CLI routes are closed; P5 bounded autonomy is active, followed by P6–P7.
  Existing provider-free acceptance implementations are retained. Native
  parity and broad framework restructuring are not prerequisites for Prime
  closure.
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
- P1's development reproduction is CLI verified. The exact installed route
  completed one Prime SDK session, five provider callbacks, two Docker-backed
  IPython cells, manual compact, oracle and cleanup, then returned the safe
  `p1-b-development/unpromoted` trace
  `sha256:a8be640bdcee9c93ea3e382729db561e4c29e071d3ff776335daac4ff572c703`.
  Post-run inspection found zero Prime Node processes and zero P1-B containers.
  Production authority promotion remains separate release work.
- P2 `prime.programmatic-long-context/v1` is CLI verified in development. Its
  installed route completed one Prime SDK session, two model callbacks, one
  Docker-backed IPython cell, the fixed corpus oracle and cleanup. It returned
  only `p2-development/unpromoted` trace
  `4ec38c0cb80010941892523610bb9cdbf8b37c213ed6c759fcd794f30d57a62e`;
  post-run inspection found zero P2 containers and zero P2 Node processes.
- P3 `prime.recursive-workflow/v1` is CLI verified through the exact installed
  route: `make prime-p3-run` passed with trace
  `sha256:b961b0ffc13a1e686a73361b9b25b9169690c942a5a84a3604d52f87e5ebe796`,
  14 focused tests passed, and zero Prime processes or temporary directories
  remained.
- P4 `prime.long-session-continuity/v1` is CLI verified in development. The
  installed route completed checkpoint persistence, direct native detach and
  exact zero-gap reattach, one compact, five model callbacks, two Docker-backed
  IPython cells, the repeated AST oracle and cleanup. `make prime-p4-run`
  exited 0 with `p4-development/unpromoted` trace
  `sha256:0bd39b78189f739dcb07123947599276d3f91e7dc24da9407be14ee283e5bebf`.
  Crash/restart replay and production promotion remain separate work.
- P5 `prime.bounded-autonomy/v1` has a fixed IPython-only diagnostic-repair
  workload, identity- and ceiling-bound two-gate trace, replay-fenced
  host-gate adapter, provider-free acceptance, and a revalidating live reducer.
  Its local fake chain is verified only; real Prime/IPython worker evidence is
  External-limited and cannot be promoted to bounded PASS.
- P6 `prime.continual-improvement/v1` has the fixed task-A/candidate/task-B
  preserve-or-exact-rollback chain over `HarnessCoordinator`, scoped evidence,
  and a global-approval-aware live reducer. It is provider-free verified only.
- P7 `prime.arc-agi-3/v1` has a single-game IPython broker trace, host score
  replay, provider-free acceptance, and distinct subset/full authorization
  reducers. No real game, model, or full-suite claim has been promoted.

## Open Problems

- Keep every compound Asterion-native row missing until Phase 3.2+ evidence
  proves the exact mandatory scenarios.
- Prove pinned/next-build compatibility only with separate exact locks and
  reviewed difference records.
- Prime source locking now hashes the declared source inputs while excluding
  only declared generated build products. The pinned `a18809e...` checkout
  reproduces cleanly, and the historical H-036/H-038 closure passed promotion. Those
  historical results do not verify the current uncommitted changes.
- Obtain separately authorized real restricted-worker evidence for the seven
  Prime products; do not infer it from local fake-chain tests or Smoke Core.
- Run final provider-free repository verification and keep any real ARC-AGI-3
  full-suite reproduction behind an exact finite operator authorization.

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
- `docs/superpowers/specs/2026-09-03-prime-ipython-workload-result-design.md`
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
4. Resume P5 of the active Prime seven-scenario worklist. Native Phase 3.2 remains a
   parallel runtime track; do not substitute it or broad framework refactoring
   for Prime end-to-end closure.
5. Keep credentials, private configuration, and execution authority external.
6. Never promote provider-free or External-limited evidence to a broader PASS.
