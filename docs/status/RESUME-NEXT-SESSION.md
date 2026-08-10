# Live Session Checkpoint

> Updated: 2026-08-10 14:09. Prime Phase 1 external-boundary closure is active.

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

## Current changes

- `cfe62b8` durably owns the exact offline workspace builds, foreground bundle
  daemon lifecycle, normalized Gateway hello, tests, operator guide, and ledger.
- `docs/status/CURRENT-STATE.md`, `DECISIONS.md`, `JOURNAL.md`, and this checkpoint
  carry the resumed program state.
- Existing `.superpowers/sdd/task-8-report.md` and `task-9-report.md` edits are
  unrelated report artifacts and must not be reverted or included casually.

## Immediate next boundary

1. Commit the managed program state files and journal correction.
2. Start an explicit Phase 2 system-parity plan from the pinned ledger without
   claiming bounded `Verified-loop` PASS.

## Invariants

- Source, credentials, provider configuration, mutable state, and evidence stay
  external and operator-owned.
- Cache, configuration, or prior evidence never grants execution authority.
- Public output must not expose prompts, credentials, private paths, provider
  payloads, raw model/application output, or host-service values.
- Provider-free PASS cannot promote bounded `Verified-loop`, system parity, or
  native parity; each requires its separately named passing boundary.
