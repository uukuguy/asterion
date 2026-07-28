# Live Session Checkpoint

> Updated: 2026-07-28 21:14. **Session remains active - Task 8 review and Plan 4 final review are next.**

## TL;DR

- Plans 1–3 remain complete and verified.
- Plan 4 Tasks 1–7 are complete and independently approved.
- Task 7 materialized the equivalent built-in source in `a9d2ff1` and made its
  evidence clean-wheel authentic in `2d78d98`.
- Task 8 implementation and closure gates are complete: 28 focused and 698
  full Python tests passed, along with lint, docs, TypeScript, Rust, wheel
  build, and all 24 promotion commands.
- Promotion used zero provider operations and no full dataset.
- The transitional source shell is deleted. The sole DCI source envelope lives
  under `src/asterion/capabilities/dci/`.

## Where things stand

- Branch/worktree:
  `feature/capability-package-architecture` in
  `.worktrees/capability-package-architecture`.
- `dci/` is the single Python/source envelope; `dci/payload/` is its closed
  portable closure.
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
- Built-in source is the generic source form; the external installed-
  distribution path is the clean-wheel proof under exact locks. Unlocked
  multi-source visibility fails closed as ambiguous.
- Every registered built-in now has independently recomputed externalization
  evidence in the wheel and passes generic source/provider conformance.
- Active contracts contain no retired DCI protocol identifiers; public CLI,
  evidence, and source-resolution redaction retain named sentinel coverage.
- climb state is tracked under `docs/status/climb/`; the adapter uses only
  provider-free local test gates and has no external push.

## Next steps

1. Commit the Task 8 implementation as
   `docs: close DCI capability package migration`.
2. Run a fresh independent Task 8 review; fix and re-review every important
   finding.
3. Record climb hypothesis H-008, update durable state, and checkpoint Task 8.
4. Run the required independent whole-Plan-4 review and final fresh gates.

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
make check
make promotion-check
```
