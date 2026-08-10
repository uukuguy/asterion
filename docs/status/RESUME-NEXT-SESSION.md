# Live Session Checkpoint

> Updated: 2026-08-10 14:55. Phase 2 Task 2 is verified; shared scenario-registry TDD is active.

## Active objective

Reach Asterion Prime functional parity in stages. Complete the real managed
Prime `Verified-loop` first, then system parity and an interchangeable native
kernel. The canonical worklist is
`docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`.

## Durable baseline

- Prime Gateway and the future native kernel are peer control providers over
  Asterion-owned authority, execution, journal, budget, recovery, and evidence.
- Provider-free Phase 1 is implemented and independently reviewed `Ready`.
- Ten real-process/fake-Prime scenarios pass with zero model-provider operations.
- Commits `75bd6fe` through `a807307` contain the provider-free closure,
  packaged resources, checkout hardening, tests, and refreshed evidence.
- Commit `cfe62b8` fixes offline setup and proves the real Node 22 bundle-daemon
  preflight without model/provider work.
- Commit `18b4a87` records the managed program state and peer-provider decision.
- `docs/superpowers/plans/2026-08-10-asterion-prime-system-parity.md`
  fixes 61 mandatory feature IDs, two exclusions, claim rules, domain delivery
  order, and the Phase 2 exit gate.
- Phase 2 Task 1 adds a provider-neutral closed/immutable parity ledger model,
  mechanical evidence-bound claim evaluation, hostile-container rejection and
  exact primary-scenario/exclusion rules.
- Phase 2 Task 2 pins all 63 feature records, 61 deterministic scenarios and
  two approved exclusions. Its metadata-only checker proves 48 exact Prime
  source files, 70 declared source records and 76 anchors at the pinned clean
  commit without starting a provider or application.
- `verified-system-parity` currently fails closed with all 61 mandatory feature
  IDs blocking; the three existing public entry points remain `implemented`,
  not PASS, until their exact parity scenarios produce admissible evidence.

## Newly verified external boundary

- `npm exec --package=node@22` supplies Node 22.23.2 without changing the host's
  default Node.
- Exact source check passes at commit
  `a18809e00ea30638584d87b3afea7285a9d7296c`, Prime 0.7.1, protocol 7, schema
  14, with zero provider operations.
- Real `prime-setup` passes in a fresh closed HOME. Setup now runs four exact
  offline workspace builds and never invokes Prime's live `generate-models`
  catalog fetch.
- Real daemon preflight passes with runtime build `beta`, zero application
  operations, and zero provider operations. Preflight directly owns one bundle
  daemon process and terminates only that exact process; removed `daemon start`
  and global `shutdown` commands are not used.
- Reusing the user's npm cache remains ruled out because URL-keyed native
  prebuilds are unpacked without a content digest check.

## Remaining Phase 1 limit

- No bounded credentials, authority file, cost ceiling, or approved private run
  configuration is present. No model-provider operation has been attempted.
- `Verified-loop` therefore remains `External-limited` only at the separately
  authorized bounded real-model gate. Provider-free and real-daemon preflight
  PASS do not grant that authority.

## Current Phase 2 state

- `3fc67d3` owns the closed parity-ledger model and mechanical claim evaluator.
- The exhaustive fixture, source-evidence checker and Make gates have passed an
  independent review with zero Critical or Important findings.
- Full Python verification passes 1674 tests; focused Pyright reports zero
  errors and zero warnings, and focused Ruff passes.
- `docs/status/CURRENT-STATE.md`, `DECISIONS.md`, `JOURNAL.md`, and this checkpoint
  carry the resumed program state.
- Existing `.superpowers/sdd/task-8-report.md` and `task-9-report.md` edits are
  unrelated report artifacts and must not be reverted or included casually.

## Immediate next boundary

1. Execute Task 3 of the Phase 2 plan test-first: create the shared 61-scenario
   registry and reporting plumbing without promoting any placeholder to PASS.

## Invariants

- Source, credentials, provider configuration, mutable state, and evidence stay
  external and operator-owned.
- Cache, configuration, or prior evidence never grants execution authority.
- Public output must not expose prompts, credentials, private paths, provider
  payloads, raw model/application output, or host-service values.
- Provider-free PASS cannot promote bounded `Verified-loop`, system parity, or
  native parity; each requires its separately named passing boundary.
