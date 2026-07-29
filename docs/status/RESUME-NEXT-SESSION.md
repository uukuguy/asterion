# Live Session Checkpoint

> Updated: 2026-07-29 17:35. **Session remains active — not a final handoff.**

## TL;DR

- Plan 1 is active in
  `.worktrees/capability-protocol-foundation` on
  `feature/capability-protocol-foundation`.
- All six Plan 1 tasks are complete and independently reviewed: runtime identity is
  `asterion.agent-runtime/v1`, and the individual capability core is
  `asterion.capability/v1`.
- Task 2 landed in `92e7113` plus review fixes `0307a0f`; Python and
  TypeScript capability contracts agree and no old executable package core
  remains.
- Task 3 added `asterion.capability-package/v1`, immutable package values,
  closed fixtures, and exact controlled-code/DCI descriptors in `04e5456`
  plus schema-alignment fix `b4102a5`.
- Task 4 established `asterion.application-assembly/v1`, independently
  ordered `capability_packages`/`capabilities`, exact built-in refs, and
  schema-declared semantic ordering in `5b17eca` plus `c021198`.
- Task 5 added closed benchmark-suite, capability-source, and source-lock
  protocols in `d82126c`, then removed the prohibited public registry source
  surface and cleared Pyright findings in `7311029`.
- Task 6 added active-surface old-identity rejection and complete installed
  wheel resource inventory checks in `d905d79`, strengthened exclusions and
  wheel coverage in `a2b2d97`, and isolated boundary fixtures in `e3b1ebd`.
- Final whole-branch review found and closed package-closure enforcement:
  installed assemblies now require exact package descriptors and capability
  membership before composition in `18ed670`.
- Fresh final verification passed 577 Python tests, all cross-language gates,
  and 20 provider-free promotion commands.
- The immediate next action is Plan 2 Task 1 in
  `2026-07-27-asterion-capability-package-sources.md`: define source-neutral,
  immutable package values under strict TDD.

## Where things stand

- Isolated baseline passed 536 Python tests plus TypeScript, Rust, lint, docs,
  and wheel build.
- Task 1 GREEN verification passed 9 focused Python tests, 14 TypeScript tests,
  and 537 full Python tests.
- Task 2 focused verification passed 47 Python tests, 15 TypeScript tests,
  example imports, and lint; independent re-review found no remaining issues.
- Task 3 focused verification passed 42 Python tests plus AJV, lint, build,
  descriptor packaging, and independent review.
- Task 4 focused verification passed 57 Python tests, 16 TypeScript tests,
  lint, and independent review with no remaining issues.
- Task 5 focused verification passed 25 Python tests, 19 TypeScript tests,
  TypeScript build, Pyright, Ruff, and independent review with no remaining
  issues.
- Task 6 verification passed 574 Python tests, `make check`, and all 20
  provider-free promotion commands; docs, TypeScript, Rust, and wheel build
  are green with provider operations `0` and full dataset `no`.
- Final post-review verification passed 577 Python tests through `make check`;
  `make promotion-check` reported `commands=20 provider_operations=0
  full_dataset=no`.
- `dci.agent-runtime/v1` remains only as the deliberate absence-test needle in
  Task 1 scope; no compatibility alias was added.
- Plans 2-4 remain dependent on completion of the six Plan 1 tasks.

## Next action

1. Create the Plan 2 task ledger/briefs and dispatch its Task 1 implementer.
2. Keep candidate/provider locator data operator-private; public source
   projections remain constrained by the Plan 1 protocol.
3. Require RED immutability/body-free representation tests before adding
   source-neutral package values.

## Boundaries and ruled-out paths

- Do not work directly on `main` or modify its uncommitted recovered baton.
- Do not preserve aliases for old `dci.*` generic protocols.
- Do not conflate individual capabilities with capability-package descriptors.
- Do not start Plan 2, generic benchmark extraction, or DCI migration before
  the Plan 1 phase gate passes.
- Do not run provider, Agent, Judge, download, setup, or full-dataset work.
