# Live Session Checkpoint

> Updated: 2026-07-29 20:36. **Session remains active — not a final handoff.**

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
- Plan 2 Task 1 added source-neutral immutable package values in `33a96c1`,
  then closed canonical identity, deep snapshot, opaque repr, hostile-body,
  and exception-context review findings through `33e31a8`.
- Plan 2 Task 2 added descriptor-relative portable payload validation in
  `07e154b`, then bound immutable verified bytes, exact declared conformance
  closure, and strict finite JSON through `8b9bc9f`.
- Plan 2 Task 3 added exact source-lock resolution in `20732bf`, then redacted
  hostile digest comparison failures in `4c9f699`; selection remains exact by
  package ref, source ID, and digest.
- Plan 2 Task 4 routes controlled-code through an explicit built-in source
  adapter in `c708053`, preserves DCI as an unregistered host-injected
  transition in `d77a14f`, and rejects extra package authority in `e0d8168`.
- Plan 2 Task 5 adds metadata-only installed-distribution discovery in
  `7ddd5a3`, then binds declared descriptor ownership and rejects standard-root
  symlink escapes through `a0873b8`.
- The immediate next action is Plan 2 Task 6: implement the explicit
  local-directory source and move transitional DCI injection onto it.

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
- Plan 2 Task 1 focused verification passed 15 model tests and 51 adjacent
  tests with Pyright and Ruff clean; independent review is approved.
- Plan 2 Task 2 focused verification passed 36 Python and 19 TypeScript tests
  with Pyright and Ruff clean; immutable-view and closure probes passed review.
- Plan 2 Task 3 focused verification passed 15 source-resolution tests and 48
  adjacent package/source/model/payload tests with Pyright, Ruff, compileall,
  `make lint`, and `git diff --check` clean.
- Plan 2 Task 4 focused built-in, installed-provider, controlled-code, DCI,
  list/describe, and injection tests passed; modified production modules are
  Pyright/Ruff clean and independent review is approved.
- Plan 2 Task 5 passed 9 real-wheel distribution tests and 46 adjacent source
  tests with Pyright/Ruff clean; rebinding and symlink escape probes passed
  independent review.
- `dci.agent-runtime/v1` remains only as the deliberate absence-test needle in
  Task 1 scope; no compatibility alias was added.
- Plans 2-4 remain dependent on completion of the six Plan 1 tasks.

## Next action

1. Dispatch Plan 2 Task 6 from the approved source plan.
2. Require explicit-root symlink, escape, factory, identity, and redaction
   failures before implementing scoped local imports.
3. Replace the DCI host-injected package object with one explicit
   local-directory source declaration; never register DCI as built-in.

## Boundaries and ruled-out paths

- Do not work directly on `main` or modify its uncommitted recovered baton.
- Do not preserve aliases for old `dci.*` generic protocols.
- Do not conflate individual capabilities with capability-package descriptors.
- Do not start Plan 2, generic benchmark extraction, or DCI migration before
  the Plan 1 phase gate passes.
- Do not run provider, Agent, Judge, download, setup, or full-dataset work.
