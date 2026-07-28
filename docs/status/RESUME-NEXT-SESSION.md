# Live Session Checkpoint

> Updated: 2026-07-28 17:17. **Session remains active — not a final handoff.**

## TL;DR

- Plans 1–3 remain complete and verified.
- Plan 4 Tasks 1–4 are complete and independently approved.
- Task 4 replaced the legacy DCI CLI with a thin application adapter in
  commits `890138d` and `af26301`; `src/asterion/dci` is absent.
- Final Task 4 verification passed 123 focused and 719 full Python tests,
  cross-language checks, docs, packaging, and promotion with zero provider
  operations.
- climb is at 4/8; H-005 / Plan 4 Task 5 is the immediate next action.

## Where things stand

- Branch/worktree:
  `feature/capability-package-architecture` in
  `.worktrees/capability-package-architecture`.
- `dci/` is the single Python/source envelope; `dci/payload/` is its closed
  portable closure.
- The transitional `dci_research` provider shell delegates to the authoritative
  payload and owns no duplicate manifests or conformance data.
- `asterion-dci` delegates to generic hosts; its adapter has no source
  lifecycle, benchmark loop, evidence writer, composer, or process runner.
- Private relative paths are anchored to the explicit env-file directory, and
  provider-free preflight fails closed for incomplete or unsafe roots.
- climb state is tracked under `docs/status/climb/`; the adapter uses only
  provider-free local test gates and has no external push.

## Next steps

1. Execute Plan 4 Task 5 from `.superpowers/sdd/task-5-brief.md`.
2. Start with the obsolete-surface absence assertions in
   `tests.test_project_boundaries`.
3. Delete the global DCI orchestrators and all 14 per-task launchers; replace
   active usage with generic `asterion benchmark` or thin `asterion-dci`
   commands.
4. Run focused and full provider-free verification, independent task review,
   then advance H-005 through `tools/climb/cycle.sh`.

## Boundaries and ruled-out paths

- Do not place Python source files inside a portable payload root.
- Do not add a validator exception for DCI.
- Do not leave compatibility wrappers for deleted launchers.
- Preserve suite IDs, task counts, plan-only defaults, explicit execution,
  resume compatibility, and private evidence semantics in active docs.
- Paths must come from application/operator configuration, never manifests.
- Preserve explicit generic execution authorization and plan-only defaults.
- Do not run provider-backed benchmarks, downloads, setup mutation, or full
  corpus reads.

## Ready-to-paste commands

```bash
cd .worktrees/capability-package-architecture
git status --short
uv run python -m unittest -v tests.test_project_boundaries
```
