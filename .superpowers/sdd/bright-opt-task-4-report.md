# Bright Optimization Task 4 Report

## Delivered

- Added the DCI-owned baseline and decomposed query-planning contracts. Public
  identity contains only the contract ID and opaque contract digest.
- Materialized the candidate append prompt only below an operator-owned `0700`
  root, with a digest-derived filename and `0400` regular file. Existing exact
  bytes are idempotent; conflicts, symlinks, FIFOs, public modes, and ownership
  mismatches fail closed.
- Bound the candidate only to Bright IR execution. The baseline preserves the
  pre-existing public effective-configuration digest; the candidate binds the
  exact prompt and its opaque query-plan contract identity.
- Added an optimization execution-config digest containing the base effective
  configuration digest and query-plan contract digest, never a private path or
  prompt body.
- Updated the packaged DCI implementation provenance and its transitive closure
  assertion for the new product module.
- Repaired the public-evidence boundary: candidate batch config and row
  identity retain only `contract_id` plus `contract_sha256`; public conversation
  strips the private system-prompt message. The private full conversation and
  recorder state retain the local prompt binding for resumability.
- Added closed validation for the candidate identity/prompt pair across batch
  preparation, native run validation, resumption, and persisted config replay.

## Verification

Passed on 2026-08-04:

```text
uv run python -m unittest -v tests.test_dci_query_planning \
  tests.test_dci_benchmark_real_executor tests.test_dci_benchmark_host \
  tests.test_dci_package_ownership tests.test_dci_reproduction \
  tests.test_dci_pathlight_capture tests.test_check_promotion \
  tests.test_dci_complete_application
# 133 tests passed

uv run pyright tests/test_dci_query_planning.py \
  tests/test_dci_benchmark_host.py tests/test_dci_benchmark_real_executor.py \
  tests/test_dci_package_ownership.py
# 0 errors, 0 warnings

uv run ruff check [Task 4 sources and tests]
git diff --check
make promotion-check
# passed
```

The candidate public-evidence test uses sentinel prompt text and a sentinel
private-root path, then verifies that batch config/rows, `conversation.json`,
the workflow bundle, Opik export envelopes, and the dashboard snapshot contain
neither sentinel. `conversation_full.json` deliberately contains both as a
private, resumable artifact.

The brief names `tests.test_dci_provenance`, but that module does not exist in
this worktree. Its applicable provenance coverage is present in
`tests.test_dci_reproduction` and `tests.test_dci_complete_application`, both
included above.

## Scope note

`tests/test_dci_complete_application.py` also changed because adding a source
to the authoritative packaged provenance closure requires the corresponding
reachable-source assertion and fixed count to remain exact.
