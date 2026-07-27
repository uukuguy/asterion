# Current State

## Project Snapshot

- Project: Asterion
- Current branch: `main`
- Theme-level focus: approved source-neutral capability-package architecture
- Project route: direct
- Canonical worklist: approved implementation plans under
  `docs/superpowers/plans/`
- Active work package: implementation not started; execution mode selection is
  the next boundary

## Current Architecture

- `src/asterion/cli.py` and product CLIs select an installed provider and exact
  application identity.
- Providers expose static assemblies resolved through deterministic package
  catalogs and composers.
- Python owns orchestration, assembly, runners, runtime adapters, and injected
  host-service protocols.
- TypeScript validates shared contracts and Node integration; Rust owns
  controlled process execution.
- DCI remains a bundled product above domain-neutral framework modules.
- The approved target hard-renames generic `dci.*` protocols to Asterion-owned
  contracts, treats built-in as one source form, and moves generic benchmark
  orchestration into Asterion.
- The approved migration proves DCI as an installed extension before exposing
  the identical portable payload through the built-in adapter.
- Installed provider resources stay package-rooted; explicit DCI operator
  configuration is rooted at the selected environment file for preflight and
  basic execution.
- `src/asterion/dci/experiment_profiles.py` owns one-use execution authority,
  exact scope/selection plans, budgets, private output identities, and immutable
  dataset bindings.
- `src/asterion/dci/cli.py` keeps reproduction plan-only by default; explicit
  execution requires exact scope, limit, private output root, and five positive
  operation/cost caps.
- `src/asterion/dci/benchmark.py` revalidates complete scope, bounded selection,
  raw dataset content, benchmark identity, and descriptor identity before
  authority consumption or Agent/Judge work.
- `src/asterion/dci/reproduction.py` compiles locked body-free RunManifest
  evidence and writes it descriptor-safely outside closed batch roots.
- Canonical `limit-N` evidence is non-full, non-comparable,
  `External-limited`, and cannot produce an acceptance PASS.

## Open Problems (theme-level)

- Plans 1-4 are approved but unimplemented; current source still contains the
  old generic protocol names, top-level `asterion.dci`, and root benchmark
  launchers.
- Provider-backed bounded reproduction still requires fresh exact finite
  authorization, an operator-selected private output root, and any
  scope-specific external datasets.
- `paper_full_executable` remains false; one-query evidence cannot establish
  full-paper or published-score reproduction.
- Existing DCI Pyright debt remains outside the repository's enforced
  provider-free check boundary.

## Key Files

### Loaded every session

- `AGENTS.md`
- `CLAUDE.md`
- `MEMORY.md` — indexed collaboration preferences and corrected feedback

### State / handoff

- `docs/status/RESUME-NEXT-SESSION.md` — current session handoff
- `docs/status/CURRENT-STATE.md` — this structural snapshot
- `docs/status/JOURNAL.md` — append-only event history
- `docs/status/INDEX.md` — status-file catalog
- `docs/status/DECISIONS.md` — active architecture decisions and rationale

### Architecture and design

- `docs/architecture/dci-capability-audit.md` — DCI capability mapping
- `docs/superpowers/specs/2026-07-27-asterion-capability-package-protocol-design.md`
- `docs/superpowers/plans/2026-07-27-asterion-capability-package-rollout.md`
- `docs/superpowers/plans/2026-07-27-asterion-capability-protocol-foundation.md`
- `docs/superpowers/plans/2026-07-27-asterion-capability-package-sources.md`
- `docs/superpowers/plans/2026-07-27-asterion-generic-benchmark-subsystem.md`
- `docs/superpowers/plans/2026-07-27-dci-capability-package-migration.md`

### Implementation entry points

- `src/asterion/cli.py` — generic provider/application CLI
- `src/asterion/runtime/protocol.py` — public runtime protocol
- `src/asterion/packages/composition.py` — deterministic package composition
- `src/asterion/runner/application.py` — resolved application execution
- `src/asterion/dci/experiment_profiles.py` — DCI profiles and authority
- `src/asterion/dci/cli.py` — DCI plan/preflight/execute orchestration
- `src/asterion/dci/verification.py` — product readiness and bounded verification
- `src/asterion/dci/benchmark.py` — bounded benchmark execution
- `src/asterion/dci/reproduction.py` — evidence compilation and comparison
- `schemas/` — canonical cross-language protocol schemas

## Resume Instructions

1. Read this file for the structural baseline.
2. Read `RESUME-NEXT-SESSION.md` for the next concrete action.
3. Read `MEMORY.md` for collaboration rules and corrected feedback.
4. Run `git status --short` and `git log --oneline -5`.
5. Select an execution mode, then start Plan 1 Task 1; do not skip directly to
   DCI migration.
6. Treat external execution as unauthorized unless the operator supplies a new
   exact scope, limit, private output root, and five finite positive caps.
7. Keep any bounded result `External-limited`; never promote it to full-paper
   or published-score reproduction.
