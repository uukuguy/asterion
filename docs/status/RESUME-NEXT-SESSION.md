# Live Session Checkpoint

> Updated: 2026-07-30 00:54. **Session remains active — not a final handoff.**

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
- Plan 2 Task 6 adds explicit local-directory loading and moves transitional
  DCI through that source in `6fff8bf`, then requires canonical absolute roots
  and exact scoped-module restoration in `13be67f`.
- Plan 2 Task 7 publishes the exact capability SDK/conformance kit in
  `50afda8`, closes executable/import/aggregate/artifact/redaction findings in
  `c2b4be3`, and aligns structural executor typing in `4e8d3fa`.
- Plan 2 Task 8 adds provider-free capability author commands and packaged
  templates in `97b2dea`, hardens trust boundaries in `9e35aff`, and keeps
  template initialization stable after compilation in `2ad265e`.
- Fresh Plan 2 Task 8 verification passed 684 Python tests, all cross-language
  checks, and 22 provider-free promotion commands; independent review found
  no remaining issue.
- Plan 2 whole-branch review found no Critical or Important issue; its one
  type-diagnostic Minor was closed in `812b209`, and final full gates passed.
- Plan 3 Task 1 defines immutable generic benchmark values in `75327b1`, then
  closes protocol, suite-closure, public-argument, and deep-freeze review gaps
  through `82449c5`; 11 focused tests and static checks pass.
- Plan 3 Task 2 adds exact closed-world suite/task resolution in `c1c0b18`,
  then closes declaration, duplicate, descriptor, redaction, and valid
  cross-platform fail-closed review gaps through `aba1503`.
- Plan 3 Task 3 adds bounded planning in `b52dc3d`, restores the approved
  request interface and pure-planning boundary in `3c413ec`, then binds
  execution intent to an injected host authorizer and composed packages in
  `fcdbaf1`.
- The immediate next action is Plan 3 Task 4: descriptor-bound private
  evidence storage and compatible resume.

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
- Plan 2 Task 6 passed 81 local/DCI/CLI tests with targeted Pyright/Ruff clean;
  root-canonicality and module-cleanup probes passed independent review.
- Plan 2 Task 7 passed expanded SDK/conformance/DCI/controlled-executor focused
  suites with production and modified-test Pyright/Ruff clean; independent
  review is approved.
- Plan 2 Task 8 passed its focused adversarial review and the full phase gates:
  `make check` and `make promotion-check` both exited 0, with provider
  operations `0` and full dataset `no`.
- `dci.agent-runtime/v1` remains only as the deliberate absence-test needle in
  Task 1 scope; no compatibility alias was added.
- Plan 2 is complete and independently reviewed.

## Next action

1. Implement Plan 3 Task 4 with descriptor, redaction, and resume RED tests.
2. Review and close private evidence storage before sequential execution.
3. Continue the approved generic benchmark subsystem plan task by task.

## Boundaries and ruled-out paths

- Do not work directly on `main` or modify its uncommitted recovered baton.
- Do not preserve aliases for old `dci.*` generic protocols.
- Do not conflate individual capabilities with capability-package descriptors.
- Do not start DCI migration before the generic benchmark subsystem phase gate
  passes.
- Do not run provider, Agent, Judge, download, setup, or full-dataset work.
