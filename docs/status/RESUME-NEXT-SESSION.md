# Live Session Checkpoint

> Updated: 2026-07-29 15:07. **Session remains active — not a final handoff.**

## TL;DR

- Plan 1 is active in
  `.worktrees/capability-protocol-foundation` on
  `feature/capability-protocol-foundation`.
- Tasks 1-3 are complete and independently reviewed: runtime identity is
  `asterion.agent-runtime/v1`, and the individual capability core is
  `asterion.capability/v1`.
- Task 2 landed in `92e7113` plus review fixes `0307a0f`; Python and
  TypeScript capability contracts agree and no old executable package core
  remains.
- Task 3 added `asterion.capability-package/v1`, immutable package values,
  closed fixtures, and exact controlled-code/DCI descriptors in `04e5456`
  plus schema-alignment fix `b4102a5`.
- The immediate next action is Plan 1 Task 4: replace the assembly wire
  protocol and add exact capability-package refs under strict TDD.

## Where things stand

- Isolated baseline passed 536 Python tests plus TypeScript, Rust, lint, docs,
  and wheel build.
- Task 1 GREEN verification passed 9 focused Python tests, 14 TypeScript tests,
  and 537 full Python tests.
- Task 2 focused verification passed 47 Python tests, 15 TypeScript tests,
  example imports, and lint; independent re-review found no remaining issues.
- Task 3 focused verification passed 42 Python tests plus AJV, lint, build,
  descriptor packaging, and independent review.
- The broad docs checker intentionally remains red on stale Markdown imports
  and one renamed local link; Task 6 owns that coherence gate.
- `dci.agent-runtime/v1` remains only as the deliberate absence-test needle in
  Task 1 scope; no compatibility alias was added.
- Plans 2-4 remain dependent on completion of the six Plan 1 tasks.

## Next action

1. Dispatch the Task 4 implementer from
   `.superpowers/sdd/task-4-brief.md`.
2. Require failing assembly identity/package-ref tests before migrating
   schemas, fixtures, built-in assemblies, Python, or TypeScript.
3. Run independent task review before advancing to Task 5.

## Boundaries and ruled-out paths

- Do not work directly on `main` or modify its uncommitted recovered baton.
- Do not preserve aliases for old `dci.*` generic protocols.
- Do not conflate individual capabilities with capability-package descriptors.
- Do not start Plan 2, generic benchmark extraction, or DCI migration before
  the Plan 1 phase gate passes.
- Do not run provider, Agent, Judge, download, setup, or full-dataset work.
