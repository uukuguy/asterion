# Live Session Checkpoint

> Updated: 2026-09-22 18:31 CST. This is a live-session recovery checkpoint, not a separate milestone handoff.

## Current objective and location

The user authorized implementation of the nine findings in `../reviews/2026-09-22-architecture-and-execution-review.md`. Work is isolated on `codex/review-implementation-20260922` at `.worktrees/review-implementation`. Do not overwrite unrelated dirty files in the main worktree.

## Verified facts

- R1/R6: `00d5008a`, `3f92df84` add exact Pi prompt acknowledgment plus settlement, retry-cycle handling, and wire validation independent of compact projection. Focused simulated-producer tests passed; real P1 model rerun has **not** been performed.
- R2: `b8f2f914`, `86f8ad63`, `11a4d00a` connect selected P3/P5/P6 provider→assembly→runner paths to injected work and sealed receipt artifacts. P3 focused 26 tests; P5/P6 focused 139 tests plus identity/cancellation tests passed. These use deterministic host/worker fixtures and do not prove live model ability.
- P6 cancellation after admission attempts one exact inverse through the same `HarnessCoordinator`; failed inverse or intervening revision is `recovery-required` with no success artifact. The older low-level tuple can carry a historical `rolled-back` failure label, so actual inverse proof must come from coordinator revision/baseline checks. Direct post-admission cancellation now raises instead of returning a false rolled-back tuple.
- R3/R4: `91ca07b1` binds composition to validated package bytes and rejects self-consumed event/artifact cycles; 55 focused tests passed.
- Final cross-boundary review found and reproduced loaded-package `source_id`/`source_kind` drift bypassing an exception guard. `6baffd9e` fails closed; both regressions and all 10 package-preparation tests passed.
- R5: `fc947d87`, `d6a888c9` close Python/Rust sidecars and process groups on cancellation, timeout, EOF, dropped future, and completed leader with a lingering descendant. `cargo test --offline --manifest-path packages/rust/controlled-executor/Cargo.toml -q` passed all package tests; Python managed executor 8 tests passed. Rust control is not an OS sandbox, and cancellation concurrent with synchronous spawn has no atomic gate.
- R7: `5d2fdbef`, `8f5bd9aa` provide optional private diagnostic correlation at package, runner, Pi prompt, Prime backend, P3 worker, and oracle boundaries while retaining public redaction. The prompt/backend/P3 focused suite passed 84 tests. Sink storage is process local unless an operator supplies another implementation.
- R8: `fe30a6cf` coalesces validated file journal reads within default append and session context refresh; 75 focused tests passed. Independent appends still revalidate old prefixes and retain quadratic cumulative parsing by design pending a separate segmented-storage contract.
- R9: `5890f261`, `49cbb550`, `11a4d00a` extract one canonical journal row codec, centralize exact Prime release inventory, decouple DCI acceptance, and move P6 candidate store behind stable service imports. Journal 76, inventory 27, and P5/P6 139 focused tests passed. `CURRENT-STATE.md`, `DECISIONS.md`, `INDEX.md`, and `MEMORY.md` are being corrected in this worktree.
- `make check` passed after the source-identity fix: 2990 Python tests, 2 skipped, plus TypeScript, lint, docs, Rust tests/clippy, and build. The source-distribution regression also passed after `0b11dd21` excluded local Node/Rust build directories.
- `make promotion-check` passed after `921200d6` added Prime resources to the exact wheel smoke inventory and `cbf4ccab` installed the declared DCI extra for isolated wheel product checks: `promotion full PASS commands=25 provider_operations=0 full_dataset=no`. The preceding failed retries were setup/resource smoke defects; their causes were reproduced and fixed. The 19 focused promotion tests and a direct minimal-wheel DCI `describe`/`acceptance` reproduction also passed.

## Current judgment and remaining boundary

Public v1 contracts stay closed. The Phase 10 shared-Pi-session draft cannot provide an independent verify process and is historical until redesigned. The review's application evidence matrix separates old live P7/P1 receipts, current deterministic composed execution, and work not rerun. Full benchmarking remains a separately authorized finite activity.

## Immediate actions

1. Preserve the clean isolated implementation branch for review. Do not merge into the dirty main worktree without addressing its separate files.
2. If a next research task needs real P1 capability evidence, run one bounded preset verification with exact receipt provenance; this session has **not rerun** it. Full benchmarks remain separately authorized.
3. Treat R8 segmented storage, durable private diagnostics, P6 durable recovery, and Phase 10 verify isolation as future design work under their existing boundaries, not as completed by this remediation.

## Working tree and process notes

- Main worktree had pre-existing dirty status files and user-owned untracked `.codex/config.toml`; preserve them.
- The temporary TypeScript `node_modules` symlink was removed; local ignored dependency directories are excluded from the sdist.
- `make check` and `make promotion-check` have exited successfully. No model or benchmark process was started by this remediation session.
