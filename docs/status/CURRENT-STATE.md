# Current State

## Project Snapshot

- Project: Asterion
- Active branch: `h024-ecosystem-capabilities`
- Theme-level focus: Prime system parity through closed, provider-free evidence
  packages, followed by Asterion-native kernel parity
- Project route: managed
- Canonical worklist:
  `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`
- Active work package: Phase 2 — Prime system parity,
  `ecosystem.capabilities` Task 10 closure

## Current Architecture

- Asterion is a composable multi-runtime framework. DCI is a reference product;
  generic framework layers remain domain-neutral.
- Python owns orchestration, exact system/application resolution, authority,
  admission, budgets, canonical journal/state, application execution, and
  public-safe evidence.
- TypeScript validates shared contracts and owns the Prime Node/Gateway
  boundary. Rust remains limited to controlled execution.
- Prime Gateway and the future native kernel are peer control providers over
  the closed Asterion agent-control contracts; neither may authorize itself or
  bypass the application runner and injected host-service boundaries.
- Provider-neutral parity ledgers and scenario registries keep implemented,
  provider-free, bounded-provider, system-parity, and native-parity claims
  distinct. Evidence promotes only the exact scenario and domain it proves.
- Prime source, credentials, provider configuration, private content, and
  generated evidence remain external and operator-owned.

## Verified Boundary

- Prime Gateway `ecosystem.capabilities` is closed at 10/10 provider-free:
  resources, extensions, packages, and MCP evidence packages reduce to ten
  immutable evidence rows.
- The exact domain checker passes for:
  `uv run python tools/check_prime_parity.py --domain ecosystem.capabilities --provider asterion.prime-gateway`.
- Every Asterion-native `ecosystem.capabilities` row remains `missing`.
- `Verified-system-parity` remains `BLOCKED` on later domains; ecosystem
  evidence does not promote interfaces, system-wide parity, or native parity.
- Climb H-025 through H-033 are recorded passed. H-034 remains pending because
  repository/promotion gates did not produce a clean PASS in the committed-
  equivalent candidate.

## Open Problems

- Resolve or explicitly quarantine pre-existing non-ecosystem repository gate
  failures before H-034 can be promoted.
- Promotion in an isolated copy currently lacks the external pinned Prime
  ecosystem source because `tools/check_promotion.py` excludes `3th-party/`.
- The next parity package after H-034 is `interfaces.operations`; do not begin
  it by claiming ecosystem closure as system parity.

## Key Files

### Loaded every session

- `AGENTS.md`
- `docs/status/INDEX.md`
- `docs/status/RESUME-NEXT-SESSION.md`
- `docs/status/JOURNAL.md`
- `docs/status/DECISIONS.md`

### Canonical program and evidence

- `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`
- `docs/superpowers/plans/2026-08-10-asterion-prime-ecosystem-parity.md`
- `docs/status/PRIME-PARITY-LEDGER.md`
- `docs/status/climb/`
- `.superpowers/sdd/ecosystem-task-10-report.md`

### Implementation entry points

- `src/asterion/control/providers/prime/ecosystem_parity_testing.py` — exact
  reducer from four provider-free ecosystem receipts to ten observations.
- `tests/test_prime_ecosystem_parity.py` — TDD coverage for reducer identity,
  fail-closed validation, exact domain closure, and registry runners.
- `tools/check_prime_parity.py` — exact domain and system-parity claim reducer.

## Resume Instructions

1. Read this structural snapshot and `RESUME-NEXT-SESSION.md`.
2. Inspect `git status --short` and recent commits before staging anything.
3. Use the parity ledger for claim boundaries; native/system claims remain
   blocked unless their exact rows pass.
4. Keep credentials, private run configuration, and execution authority
   external.
5. Never promote provider-free or pre-existing-failure evidence to a broader
   PASS.
