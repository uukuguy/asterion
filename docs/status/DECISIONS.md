# Architectural Decisions

## Index

| ID | Status | Decision |
|---|---|---|
| D-2026-07-26-01 | 🟢 active | Anchor explicit operator configuration to the environment-file directory |
| D-2026-07-31-02 | 🟢 active | Complete every DCI instance's 50-case result before considering full datasets |
| D-2026-08-10-03 | 🟢 active | Stage Prime-managed and native kernels as peer control providers |
| D-2026-08-27-04 | 🟢 active | Quiesce host-owned ecosystem projections before cleanup |

## D-2026-07-26-01 — Operator configuration root

- Status: 🟢 active
- Decision: The parent directory of an explicit environment file is the root
  for relative Pi, Agent, corpus, and output paths during DCI verification.
  Installed provider resources remain rooted under the package.
- Rationale: Package resources and operator-owned configuration are different
  trust boundaries. Using the package root for both produced false missing
  setup diagnostics and could make preflight disagree with basic execution.
- Consequence: `make doctor` passes the repository `.env` explicitly, and
  preflight/basic resolve the same operator paths without changing generic
  provider discovery or package resource ownership.
- Evidence: commit `2358d49`; `make doctor`; `make check`;
  `make promotion-check`.

## D-2026-07-31-02 — DCI progressive evaluation order

- Status: 🟢 active
- Decision: For every real DCI instance, finish the executable 50-case (or
  smaller complete) run, scoring, and exact-resume closure before starting any
  instance's full dataset run.
- Rationale: This yields comparable, bounded, evidence-backed version results
  across the whole instance list before spending full-dataset budget.
- Consequence: Results are recorded as `50/total`; a full benchmark stays
  deferred until all listed 50-case versions have passed.

## D-2026-08-10-03 — Peer long-running control providers

- Status: 🟢 active
- Decision: First deliver Prime Agent through a managed TypeScript Gateway, then
  implement an Asterion-native kernel as a peer provider over the same closed
  Python-owned control contracts.
- Rationale: Prime delegation supplies a high-value long-running behavior oracle
  sooner and at lower initial risk. A shared provider-neutral authority,
  execution, recovery, and evidence plane prevents Prime-specific semantics from
  becoming the framework kernel and preserves a later native implementation.
- Consequence: Phase 1 must reach the bounded Prime `Verified-loop` gate before
  it is used as a differential oracle. System parity and native parity remain
  separate named phases and cannot be inferred from provider-free evidence.
- Evidence: `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`;
  commits `75bd6fe`, `ea7a53f`, `7c202ed`.

## D-2026-08-27-04 — Quiescent ecosystem cleanup boundary

- Status: 🟢 active
- Decision: The host owns the ecosystem private namespace and must quiesce all
  projection consumers before rollback or close. Cleanup detects pre-existing
  drift and fails closed, but does not claim protection from hostile same-UID
  code retaining write-capable descendant directory descriptors during cleanup.
- Rationale: Darwin/Python exposes name-relative deletion but no portable
  conditional unlink or rmdir by held target descriptor. The stronger
  concurrent retained-fd guarantee cannot be implemented honestly without a
  new native or helper-process isolation boundary.
- Consequence: Cleanup keeps explicit retry-safe phases through tree removal and
  parent fsync. Missing or mismatched names retain ownership. Ambiguous
  descriptor-close failures are terminal and the numeric fd is never retried.
- Evidence: approved option 1 on 2026-08-27; H-024 Task 2 feasibility audit;
  `docs/superpowers/specs/2026-08-23-asterion-prime-ecosystem-parity-design.md`.
