# Live Session Checkpoint

> Updated: 2026-07-28 19:20. **Session remains active — not a final handoff.**

## TL;DR

- Plans 1–3 remain complete and verified.
- Plan 4 Tasks 1–6 are complete and independently approved.
- Task 6 proved DCI as a clean-environment installed extension in `19e3135`
  and closed exact-lock, source-ID, snapshot-copy, and SDK gaps in `cb813ea`.
- Final Task 6 verification passed 34 focused and 691 full Python tests,
  cross-language checks, docs, packaging, and promotion with zero provider
  operations.
- climb is at 6/8; H-007 / Plan 4 Task 7 is the immediate next action.

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
- climb state is tracked under `docs/status/climb/`; the adapter uses only
  provider-free local test gates and has no external push.

## Next steps

1. Execute Plan 4 Task 7 from `.superpowers/sdd/task-7-brief.md`.
2. Start with the missing built-in DCI provider and form-equivalence test.
3. Prove built-in, installed-distribution, and explicit-local forms have
   identical payload, manifest, binding, conformance, plan, and public-result
   identities; unlocked multi-source resolution must remain ambiguous.
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
uv run python -m unittest -v tests.test_dci_source_form_equivalence
```
