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
- `capability_sdk` keeps underscored private helper aliases for built-in DCI in-process artifacts; they are intentionally omitted from `__all__`.
