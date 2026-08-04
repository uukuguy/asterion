# Bright Optimization Task 5 Report

## Delivered

- Added the DCI-only provider-free `pathlight optimization prepare` and `status`
  coordinator, with an immutable private Bright 4 x 10 plan and no execution
  authority.
- Bound the query-decomposition proposal, coverage prerequisite, finding,
  scope, source lock, exact four Bright selections, baseline/candidate generic
  Variant identities, Task 4 execution-config identities, limits, gate-report
  digest, and output-root device/inode into the plan and authorization.
- Added a DCI-owned, canonical mode-0600 authorization gate report.  It is
  emitted only from a real, coverage-complete `DciDiagnosisReport` during the
  diagnosis command's existing atomic publish; it binds the generic diagnosis
  bundle and safe coverage experiment, plan, receipt, and evidence-set
  identities without including private content.
- `prepare` now requires an exact absolute
  `--gate-report-file`, closes it against the diagnosis/proposal/scope, and
  rejects missing, incomplete, tampered, non-0600, symlink, FIFO, and
  oversized reports before loading a provider or publishing a plan.
- Added a strict 0600 authorization reader that rejects noncanonical documents,
  unknown fields, bad digests, mode/owner/symlink/FIFO failures through the
  private-file boundary, boolean integers, and every plan-bound mismatch.
- Routed `asterion-dci pathlight optimization` through the DCI product CLI.

## Safety notes

- `prepare` passes a deliberately absent dotenv path to operator-config loading;
  it consumes only caller-provided environment and does not load providers,
  execute benchmarks, or create authorization.
- Public command summaries contain counts, limits, and opaque digests only. They
  exclude selected case IDs, private prompt/body content, paths, and provider
  configuration.
- The two Variant identities share every generic Variant input except the
  query-plan-derived prompt/change identities; each task also binds its exact
  Variant and Task 4 execution-config digest.
- Before Task 6 creates a receipt schema, `status` rejects every non-empty
  receipt directory rather than interpreting an unauthenticated receipt.
- One minimal direct dependency change permits the existing descriptor-safe
  staged-tree publisher to hard-link a read-only `0400` candidate prompt in
  addition to its existing `0600` private files. The query-planning contract
  requires that prompt mode and existing query-planning tests pass unchanged.

## Verification

- `uv run python -m unittest -v tests.test_dci_pathlight_optimization_cli tests.test_dci_pathlight_diagnosis tests.test_dci_pathlight_cli tests.test_dci_query_planning tests.test_dci_benchmark_host` — 55 passing.
- `uv run pyright src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py src/asterion/applications/dci_agent_lite/pathlight_cli.py src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py tests/test_dci_pathlight_optimization_cli.py tests/test_dci_pathlight_diagnosis.py tests/test_dci_pathlight_cli.py` — 0 errors.
- `uv run ruff check src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py src/asterion/applications/dci_agent_lite/pathlight_cli.py src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py tests/test_dci_pathlight_optimization_cli.py tests/test_dci_pathlight_diagnosis.py tests/test_dci_pathlight_cli.py` — clean.
- `git diff --check` — clean.
