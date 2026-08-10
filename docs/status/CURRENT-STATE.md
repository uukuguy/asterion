# Current State

## Project Snapshot

- Project: Asterion
- Active branch: `main`
- Theme-level focus: Prime functional parity through a managed provider, then
  an interchangeable Asterion-native kernel
- Project route: managed
- Canonical worklist:
  `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`
- Active work package: Phase 1 — Prime verifiable long-running closure

## Current Architecture

- Asterion is a composable multi-runtime framework. DCI is a reference product;
  generic framework layers remain domain-neutral.
- Python owns orchestration, exact system/application resolution, authority,
  admission, budgets, canonical journal/state, application execution, and
  public-safe evidence.
- TypeScript validates shared contracts and owns the Prime Node/Gateway boundary.
  Rust remains limited to controlled execution.
- Prime Gateway and the future native kernel are peer control providers over the
  closed Asterion agent-control contracts; neither may authorize itself or bypass
  the application runner and injected host-service boundaries.
- Prime source, credentials, provider configuration, private content, and
  generated evidence remain external and operator-owned.
- Capability packages, application assemblies, runtimes, and catalogs preserve
  exact identities, deterministic composition, and fail-closed ambiguity.

## Open Problems

- Separately authorized bounded `Verified-loop` evidence and private run binding
- Complete mandatory Prime system-parity ledger and conformance coverage
- Asterion-native long-running kernel and differential parity
- Long-tail Prime ecosystem and operational parity

## Key Files

### Loaded every session

- `AGENTS.md`
- `docs/status/INDEX.md`
- `docs/status/RESUME-NEXT-SESSION.md`
- `docs/status/JOURNAL.md`
- `docs/status/DECISIONS.md`

### Canonical program and evidence

- `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`
- `docs/superpowers/plans/2026-08-10-asterion-prime-verified-loop.md`
- `docs/status/PRIME-PARITY-LEDGER.md`
- `docs/guides/prime-control-operator-guide.md`

### Implementation entry points

- `src/asterion/control/` — provider-neutral authority, execution, recovery,
  children, journals, and provider bindings
- `src/asterion/control/providers/prime/` — Python Prime control client/factory
- `packages/typescript/prime-gateway/` — Prime daemon boundary and durable bridge
- `tools/setup_prime_agent.py` — exact external Prime checkout setup
- `tools/verify_prime_loop.py` — provider-free, preflight, and bounded gates

## Resume Instructions

1. Read this structural snapshot and `RESUME-NEXT-SESSION.md`.
2. Inspect `git status --short` and recent commits.
3. Use the canonical worklist and parity ledger for package selection and claims.
4. Keep credentials, private run configuration, and execution authority external.
5. Never promote provider-free or External-limited evidence to a broader PASS.
