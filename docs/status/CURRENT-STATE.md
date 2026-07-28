# Current State

## Project Snapshot

- Project: Asterion
- Current branch: `feature/capability-package-architecture`
- Theme-level focus: external-first DCI capability-package migration
- Project route: direct
- Canonical worklist: approved implementation plans under
  `docs/superpowers/plans/`
- Active work package: Plan 4 complete; awaiting branch integration direction

## Current Architecture

- `src/asterion/cli.py` and product CLIs select an installed provider and exact
  application identity.
- Providers expose static assemblies resolved through deterministic package
  catalogs and composers.
- Python owns orchestration, assembly, runners, runtime adapters, and injected
  host-service protocols.
- TypeScript validates shared contracts and Node integration; Rust owns
  controlled process execution.
- DCI remains a bundled product above domain-neutral framework modules, with
  one package-owned implementation and resource tree.
- Generic protocols are Asterion-owned; built-in is one source form; generic
  benchmark planning, execution, evidence, cancellation, and resume are
  implemented under `src/asterion/benchmarks/`.
- Source-neutral built-in, distribution, and explicit-local adapters resolve
  exact portable payloads through public capability SDK contracts.
- The DCI Python/source envelope owns a closed portable `dci@1.0.0` payload
  below `src/asterion/capabilities/dci/payload/`, with exact 12/13/15-task
  GitHub, paper-main, and union suites.
- All DCI domain implementation and 38 packaged resources now live below
  `src/asterion/capabilities/dci/`; the legacy `asterion.dci` namespace is
  absent.
- Installed host-service entry points, TypeScript resource synchronization,
  and wheel contents all resolve the authoritative package-owned
  implementation and payload. The transitional provider shell is absent.
- Application assembly inventory and acceptance identities are application
  owned and injected into package verification as immutable values.
- `asterion-dci` is a thin `dci_agent_lite` adapter over generic application
  and benchmark hosts. It translates private operator configuration, performs
  provider-free readiness checks, and uses the generic built-in package source
  lifecycle.
- Global DCI orchestrators and all per-task shell launchers are absent.
  Package-owned paper metadata names exact logical benchmark binding IDs, and
  active usage routes through generic suite planning/execution/resume.
- The approved migration proves DCI as an installed extension before exposing
  the identical portable payload through the built-in adapter.
- The installed external DCI fixture now proves clean-environment metadata
  discovery, exact source locking, selected-only provider import, conformance,
  and synthetic execution against the authoritative portable payload.
- Built-in, installed-distribution, and explicit-local DCI forms now share
  exact payload, manifest, binding, conformance, synthetic plan, and public
  result identities; unlocked multi-source visibility fails ambiguous.
- Installed provider resources stay package-rooted; explicit DCI operator
  configuration is rooted at the selected environment file for preflight and
  basic execution.
- DCI package implementation owns one-use execution authority, exact
  scope/selection plans, budgets, private output identities, and immutable
  dataset bindings.
- Generic benchmark execution remains plan-only by default and requires
  explicit `--execute`; private DCI roots remain application-owned and
  redacted.
- Package-owned benchmark code revalidates complete scope, bounded selection,
  raw dataset content, benchmark identity, and descriptor identity before
  authority consumption or Agent/Judge work.
- Package-owned reproduction code compiles locked body-free RunManifest
  evidence and writes it descriptor-safely outside closed batch roots.
- Canonical `limit-N` evidence is non-full, non-comparable,
  `External-limited`, and cannot produce an acceptance PASS.

## Open Problems (theme-level)

- All eight Plan 4 tasks are implemented, independently approved, whole-branch
  reviewed, and verified. No Plan 4 implementation or review finding remains.
- Branch integration, PR creation, merge, or push requires a separate operator
  decision and was not performed by this climb session.
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
- `docs/status/climb/research-tree.md` — generated Plan 4 progress and recovery

### Implementation entry points

- `src/asterion/cli.py` — generic provider/application CLI
- `src/asterion/runtime/protocol.py` — public runtime protocol
- `src/asterion/packages/composition.py` — deterministic package composition
- `src/asterion/runner/application.py` — resolved application execution
- `src/asterion/applications/dci_agent_lite/cli.py` — thin DCI CLI adapter
- `src/asterion/applications/dci_agent_lite/operator_config.py` — private
  operator translation and provider-free readiness
- `src/asterion/applications/dci_agent_lite/provider.py` — DCI application
  ownership, exact assemblies, and injected acceptance inventory
- `src/asterion/capabilities/dci/implementation/` — DCI domain implementation
- `src/asterion/capabilities/dci/resources/` — authoritative packaged resources
- `src/asterion/capabilities/dci/payload/` — exact portable DCI package closure
- `schemas/` — canonical cross-language protocol schemas

## Resume Instructions

1. Read this file for the structural baseline.
2. Read `RESUME-NEXT-SESSION.md` for the next concrete action.
3. Read `MEMORY.md` for collaboration rules and corrected feedback.
4. Run `git status --short` and `git log --oneline -5`.
5. Treat Plan 4 as complete; await operator direction for branch integration.
6. Treat external execution as unauthorized unless the operator supplies a new
   exact scope, limit, private output root, and five finite positive caps.
7. Keep any bounded result `External-limited`; never promote it to full-paper
   or published-score reproduction.
