# Bright Optimization Task 4 Report

## Delivered

- Added the DCI-owned baseline and decomposed query-planning contracts. Public
  identity contains only the contract ID and opaque contract digest.
- Materialized the candidate append prompt only below an operator-owned `0700`
  root, with a digest-derived filename and `0400` regular file. Existing exact
  bytes are idempotent; conflicts, symlinks, FIFOs, public modes, and ownership
  mismatches fail closed.
- Bound the candidate only to Bright IR execution. The baseline preserves the
  pre-existing request exactly; the candidate changes only
  `BenchmarkRequest.append_system_prompt_file`.
- Added an optimization execution-config digest containing the base effective
  configuration digest and query-plan contract digest, never a private path or
  prompt body.
- Updated the packaged DCI implementation provenance and its transitive closure
  assertion for the new product module.

## Verification

Passed on 2026-08-04:

```text
uv run python -m unittest -v tests.test_dci_query_planning \
  tests.test_dci_benchmark_real_executor tests.test_dci_benchmark_host \
  tests.test_dci_reproduction tests.test_check_promotion \
  tests.test_dci_complete_application
# 105 tests passed

uv run pyright src/asterion/capabilities/dci/implementation/research/query_planning.py \
  src/asterion/applications/dci_agent_lite/benchmark_executor.py \
  src/asterion/applications/dci_agent_lite/benchmark_host.py
# 0 errors, 0 warnings

uv run ruff check [Task 4 sources and tests]
git diff --check
make promotion-check
```

The brief names `tests.test_dci_provenance`, but that module does not exist in
this worktree. Its applicable provenance coverage is present in
`tests.test_dci_reproduction` and `tests.test_dci_complete_application`, both
included above.

## Scope note

`tests/test_dci_complete_application.py` also changed because adding a source
to the authoritative packaged provenance closure requires the corresponding
reachable-source assertion and fixed count to remain exact.
