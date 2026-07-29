# Plan 2 Task 7 Report: Publish capability SDK and conformance kit

## RED
- `uv run python -m unittest -v tests.test_capability_sdk tests.test_capability_conformance` initially failed with missing `asterion.capability_sdk` imports and private built-in implementation imports.
- Added a real built-in conformance test; it failed with `('benchmark binding is missing', 'conformance vector is invalid')` before the controlled-code benchmark binding and vector semantics fix.

## GREEN
- Created `asterion.capability_sdk` with the exact 11-name public `__all__`.
- Added `CapabilityPackageProvider` as the selected-provider protocol with only `load_package()`.
- Added provider-free `run_capability_conformance()` covering immutable/safe aggregate output, identity/digest/source validation, manifest closure, implementation binding completeness/uniqueness, benchmark binding ownership/uniqueness, conformance vector checks, redaction, no opaque execution, and `BaseException` preservation.
- Allowed public provider authors to pass `(CapabilityRef, implementation)` pairs into `InstalledCapabilityPackage` without importing private binding classes.
- Migrated controlled-code and DCI implementation modules to SDK/package-owned imports for the AST gate.
- Added package-owned DCI runtime/provenance helpers to avoid runtime/product imports from capability implementation modules.
- Added a non-executed controlled-code benchmark conformance binding.

## Verification
- `uv run python -m unittest -v tests.test_capability_sdk tests.test_capability_conformance tests.test_builtin_controlled_code_application tests.test_dci_complete_application` -> PASS, 47 tests.
- `uv run pyright src/asterion/capability_sdk src/asterion/capability_packages/model.py src/asterion/capabilities/builtin.py src/asterion/capabilities/controlled_code/implementation.py src/asterion/capabilities/dci_research/_runtime.py src/asterion/capabilities/dci_research/_provenance.py src/asterion/capabilities/dci_research/implementation.py src/asterion/capabilities/dci_research/complete.py src/asterion/services/controlled_executor_jsonl.py tests/test_capability_sdk.py tests/test_capability_conformance.py` -> PASS, 0 errors.
- `uv run ruff check src tests tools` -> PASS.
- `uv run python -m compileall -q src tests tools` -> PASS.
- `git diff --check` -> PASS.

## Concerns
- Full-repo Pyright was not used as a gate because it reports many pre-existing diagnostics outside the Task 7 surface.

## Review Fix RED
- `uv run python -m unittest -v tests.test_capability_sdk tests.test_capability_conformance tests.test_dci_complete_application tests.test_dci_research_capability tests.test_controlled_executor_jsonl` failed with 16 failures and 1 error before production fixes:
  - SDK namespace still exposed `_InProcessArtifactPayload`.
  - DCI `local_provider.py` imported five private framework modules.
  - Pair conversion and conformance accepted missing/non-callable/hostile `execute`.
  - Mutable duck installed packages reached payload validation instead of exact installed-package rejection.
  - DCI aggregate omitted legacy `ndcg_at_10`, resolution, timing, totals, and averages.
  - DCI `_runtime.py` accepted artifact extras, uppercase/short sha256, and blank uri.
  - controlled-executor structural request leaked `SECRET-TARGET` before redaction.

## Review Fix GREEN
- Removed all underscored/private helper aliases from `asterion.capability_sdk`; exact public surface remains 11 names.
- Validated callable `execute` at public implementation-pair conversion and provider-free conformance without invoking provider code; hostile `Exception` paths are body-free and `BaseException` propagates where provider attributes are read.
- Made conformance require exact `InstalledCapabilityPackage`, tuple invariants, exact source identifier validation, and exact implementation binding values.
- Strengthened the built-in package AST gate to enumerate every `.py`, resolve relative imports, and detect `__import__` plus aliased `importlib.import_module`.
- Moved DCI private artifact projection, aggregate behavior, and payload digest identity into DCI package-owned helpers; DCI built-in package sources now import only SDK, stdlib, or DCI-owned modules.
- Matched previous DCI aggregate behavior with regression comparison against `asterion.dci.analysis.aggregate_results`.
- Tightened DCI runtime artifact event validation to required+optional keys only and canonical lowercase 64-hex sha256.
- Moved controlled-executor structural `request.target` reads into a redacted/context-free validation block while preserving `BaseException`.

## Review Fix Verification
- RED: `uv run python -m unittest -v tests.test_capability_sdk tests.test_capability_conformance tests.test_dci_complete_application tests.test_dci_research_capability tests.test_controlled_executor_jsonl` -> FAIL, 16 failures and 1 error before production fixes.
- GREEN: `uv run python -m unittest -v tests.test_capability_sdk tests.test_capability_conformance tests.test_builtin_controlled_code_application tests.test_dci_complete_application tests.test_dci_research_capability tests.test_controlled_executor_jsonl tests.test_controlled_code_application` -> PASS, 67 tests.
- `uv run pyright src/asterion/capability_sdk src/asterion/capability_packages/model.py src/asterion/capabilities/dci_research src/asterion/capabilities/execution.py src/asterion/services/controlled_executor_jsonl.py` -> PASS, 0 errors.
- `uv run ruff check src tests tools` -> PASS.
- `uv run python -m compileall -q src tests tools` -> PASS.
- `git diff --check` -> PASS.

## Final Typed API Fix
- RED: `uv run python -m unittest -v tests.test_controlled_executor_jsonl` failed because `ControlledExecutorJsonlClient.execute` still annotated `request` as exact `ControlledExecutionRequest` while runtime intentionally accepts package-owned structural requests.
- GREEN: changed the request annotation to `object`, documented normalization to exact `ControlledExecutionRequest`, and kept hostile structural request redaction plus `BaseException` preservation.
- `uv run python -m unittest -v tests.test_controlled_executor_jsonl tests.test_controlled_code_application tests.test_builtin_controlled_code_application` -> PASS, 11 tests.
- `uv run pyright src/asterion/services/controlled_executor_jsonl.py src/asterion/capabilities/controlled_code/implementation.py tests/test_controlled_executor_jsonl.py tests/test_controlled_code_application.py tests/test_builtin_controlled_code_application.py` -> PASS, 0 errors.
- `uv run ruff check src tests tools` -> PASS.
- `uv run python -m compileall -q src tests tools` -> PASS.
- `git diff --check` -> PASS.
