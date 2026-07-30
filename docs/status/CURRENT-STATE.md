# Current State

## Project Snapshot

- Project: Asterion
- Active branch: `main`
- Theme: source-neutral capability packages and generic benchmark execution
- Runnable DCI closure Tasks 1–9: implemented; first real instance is verified across all 50 cases
- Next action: implement the next exact instance from the DCI benchmark backlog

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

- `asterion-dci benchmark instances`, source locking, and planning are
  implemented and provider-free.
- The installed product host supports explicitly authorized run/resume for the
  provider-free local fixture and bounded Bamboogle instance. It injects exact
  implementations, cancellation, and private evidence only after authority.
- Credentials, provider settings, datasets, corpora, paths, private environment,
  and optional amount remain operator-owned and outside portable/public values.
- A monetary amount is not a generic authorization requirement.
- Real Bamboogle binds the `asterion-safe/pi` Agent/prompt/Judge contracts,
  defaults to one case, and permits a finite 50-case run. The complete
  GitHub-sample50 run is verified; paper-full125 reproduction remains unimplemented
  and requires separate finite-budget governance.
- Archive and registry source forms remain deferred pending a separate security
  and lifecycle design.

## Verification State

- The installed-wheel subprocess test executes and resumes all 15 local fixture
  tasks using only installed resources: `Verified-local`.
- The Bamboogle path has fake Agent/Judge E2E verification, exact 50-case
  provider-free planning, and a real full50 `Verified-full` run.
- Main-workspace run `run-e8ea4a0db373482b9a849d8f8ace7790` completed all
  50 cases with 50 judged, 41 correct, 82% accuracy, and zero failed runs.
  Exact resume completed in zero seconds without adding evidence or generation.
- `make check` and `make promotion-check` pass on integrated `main`. The
  completed capability-protocol worktree and branch have been removed.
- A passing command is required before any final state is labelled Verified.
  Provider-free checks never establish paper-score reproduction.

## Key Files

- `AGENTS.md` — repository invariants
- `docs/status/RESUME-NEXT-SESSION.md` — current handoff
- `docs/status/JOURNAL.md` — append-only event history
- `docs/status/DECISIONS.md` — active architecture decisions
- `docs/status/DCI-BENCHMARK-INSTANCES.md` — exact instance backlog
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
3. Keep private resources and credentials outside repository state.
4. Select and implement the next exact instance from
   `DCI-BENCHMARK-INSTANCES.md`, preserving finite execution limits.
5. Never promote bounded or provider-free evidence to full-paper reproduction.
