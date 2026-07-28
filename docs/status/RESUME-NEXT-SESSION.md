# Live Session Checkpoint

> Updated: 2026-07-28 20:09. **Session remains active — not a final handoff.**

## TL;DR

- Plans 1–3 remain complete and verified.
- Plan 4 Tasks 1–7 are complete and independently approved.
- Task 7 materialized the equivalent built-in source in `a9d2ff1` and made its
  evidence clean-wheel authentic in `2d78d98`.
- Final Task 7 verification passed 102 focused and 693 full Python tests,
  cross-language checks, docs, packaging, and promotion with zero provider
  operations.
- climb is at 7/8; H-008 / Plan 4 Task 8 is the immediate next action.

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
- Old orchestrator/launcher files and active references are absent; historical
  retained references carry precise superseded notices, with current Plan 4
  narrowly exempt for its deletion contract.
- The external DCI wheel carries the authoritative payload bytes, imports only
  the public capability SDK, remains unimported during metadata/payload
  discovery, and loads only through its exact identifier-shaped source lock.
- Built-in, installed-distribution, and explicit-local forms produce identical
  public fingerprints under exact locks; all three visible without a lock fail
  closed as ambiguous.
- climb state is tracked under `docs/status/climb/`; the adapter uses only
  provider-free local test gates and has no external push.

## Next steps

1. Execute Plan 4 Task 8 from `.superpowers/sdd/task-8-brief.md`.
2. Add final structural/privacy assertions, then remove the transitional
   `dci_research` shell and any remaining obsolete identifiers or paths.
3. Update architecture, security, CLI, and operator documentation for the
   external-first package/source model and explicit execution authority.
4. Run focused and full provider-free verification, independent task review,
   then advance H-006 through `tools/climb/cycle.sh`.

## Boundaries and ruled-out paths

- Do not place Python source files inside a portable payload root.
- Do not add a validator exception for DCI.
- Do not special-case DCI in generic source resolution or execution.
- Do not let metadata-only discovery import the selected provider or adjacent
  packages.
- Installed payload bytes, suites, identities, and implementation bindings
  must match the authoritative portable package exactly.
- Preserve explicit generic execution authorization and plan-only defaults.
- Do not run provider-backed benchmarks, downloads, setup mutation, or full
  corpus reads.

## Ready-to-paste commands

```bash
cd .worktrees/capability-package-architecture
git status --short
uv run python -m unittest -v tests.test_project_boundaries tests.test_distribution tests.test_dci_package_ownership tests.test_dci_source_form_equivalence
```
