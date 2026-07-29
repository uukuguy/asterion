# Current State

## Project Snapshot

- Project: Asterion
- Active branch: `feature/capability-protocol-foundation`
- Theme: source-neutral capability packages and generic benchmark execution
- Plans 1–4: implemented; final Plan 4 integration gates are the current boundary
- Next action: review and integrate the completed branch

## Current Architecture

- Asterion owns the public runtime, capability, capability-package, application
  assembly, source, source-lock, and benchmark-suite contracts.
- Python owns orchestration, deterministic composition, source resolution,
  application assembly, benchmark planning/execution, and runtime adapters.
- TypeScript validates shared contracts and Node integration. Rust owns
  controlled process execution.
- Built-in, installed-distribution, and explicit local-directory capability
  packages are equivalent source forms. Resolution has no hidden precedence and
  exact ambiguity requires a source lock.
- DCI is `dci@1.0.0`, one capability-package implementation of the generic
  Asterion benchmark subsystem. Generic framework modules do not import it.
- `src/asterion/capabilities/dci/` owns the DCI portable payload, suites,
  implementation, resources, and provider. The old top-level and transitional
  owners are absent.
- `src/asterion/applications/dci_agent_lite/` owns the product application,
  assemblies, provider exposure, and thin `asterion-dci` adapter.
- The DCI package passed external-first clean-wheel conformance before built-in
  registration. Built-in, distribution, and local forms have equivalent public
  behavior.
- Global DCI benchmark launchers and per-task shell scripts are absent. DCI
  suite bindings translate private operator inputs into generic task
  invocations inside the package.

## Execution Boundary

- `asterion-dci benchmark plan` is implemented and provider-free.
- The installed CLI has no execution authority. Run/resume require an embedding
  host's fresh authorization, exact source selection, injected implementations,
  executor, cancellation, and private evidence service.
- Credentials, provider settings, datasets, corpora, paths, private environment,
  and optional amount remain operator-owned and outside portable/public values.
- A monetary amount is not a generic authorization requirement.
- Full datasets and paper reproduction require separate finite-budget
  governance and were not run during this migration.
- Archive and registry source forms remain deferred pending a separate security
  and lifecycle design.

## Verification State

- Task-level tests and reviews for Plans 1–3 and Plan 4 Tasks 1–7 are complete.
- Plan 4 Task 8 adds permanent ownership, portable built-in, active-document,
  wheel inventory, privacy, and source-form boundary assertions.
- A passing command is required before any final state is labelled Verified.
  Provider-free checks never establish paper-score reproduction.

## Key Files

- `AGENTS.md` — repository invariants
- `docs/status/RESUME-NEXT-SESSION.md` — current handoff
- `docs/status/JOURNAL.md` — append-only event history
- `docs/status/DECISIONS.md` — active architecture decisions
- `docs/superpowers/plans/2026-07-27-dci-capability-package-migration.md`
- `docs/architecture/benchmark-subsystem.md`
- `docs/architecture/composable-packages.md`
- `docs/security.md`
- `src/asterion/benchmarks/` — generic benchmark subsystem
- `src/asterion/capabilities/dci/` — DCI capability package
- `src/asterion/applications/dci_agent_lite/` — DCI application adapter

## Resume Instructions

1. Read this file and `RESUME-NEXT-SESSION.md`.
2. Run `git status --short` and `git log --oneline -10`.
3. Confirm the final Task 8 commit and named gates before integration.
4. Treat all external execution as unauthorized unless the operator supplies a
   new explicit authorization and required private services.
5. Never promote bounded or provider-free evidence to full-paper reproduction.
