### Plan 2 Task 4 Report

Status: PASS

RED:
- `uv run python -m unittest discover -s tests -p 'test_builtin_capability_source.py' -v` initially failed with `ModuleNotFoundError: No module named 'asterion.capabilities.builtin'`.
- After the first implementation pass, the same suite failed on payload-error context redaction and unresolved temp-root payload opening; those drove adapter/context and root canonicalization fixes.
- `uv run python -m unittest discover -s tests -p 'test_installed_application_provider.py' -v` initially failed because `InstalledApplication` still expected raw `catalog_roots`/`implementations` in tests, proving the model boundary changed.

GREEN:
- `uv run python -m unittest discover -s tests -p 'test_builtin_capability_source.py' -v` -> 6 tests OK.
- `uv run python -m unittest discover -s tests -p 'test_installed_application_provider.py' -v` -> 12 tests OK.
- `uv run python -m unittest discover -s tests -p 'test_builtin_controlled_code_application.py' -v` -> 2 tests OK.
- `uv run asterion list` -> metadata for `controlled-code` and `dci-agent-lite`; no selected provider load.
- `uv run python -m unittest discover -s tests -p 'test_capability_package_model.py' -v` -> 15 tests OK.
- `uv run python -m unittest discover -s tests -p 'test_capability_package_payload.py' -v` -> 10 tests OK.
- `uv run python -m unittest discover -s tests -p 'test_capability_source_resolution.py' -v` -> 15 tests OK.
- `uv run python -m unittest discover -s tests -p 'test_controlled_code_application.py' -v` -> 4 tests OK.
- `uv run pyright src/asterion/capabilities/builtin.py src/asterion/capability_packages/sources/builtin.py src/asterion/applications/provider.py src/asterion/applications/controlled_code/provider.py src/asterion/cli.py` -> 0 errors.
- `uv run ruff check src/asterion/capabilities/builtin.py src/asterion/capability_packages/sources/builtin.py src/asterion/applications/provider.py src/asterion/applications/controlled_code/provider.py src/asterion/cli.py tests/test_builtin_capability_source.py tests/test_installed_application_provider.py tests/test_builtin_controlled_code_application.py` -> all checks passed.
- `uv run python -m compileall -q src/asterion tests/test_builtin_capability_source.py tests/test_installed_application_provider.py tests/test_builtin_controlled_code_application.py` -> PASS.

Concerns:
- DCI is intentionally not registered as a built-in capability source in this task.
- Full `make check` was intentionally not run per resume instruction.

## Important DCI Regression Fix

Status: PASS

RED:
- `uv run python -m unittest -v tests.test_asterion_cli.AsterionCliTests.test_dci_list_provider_and_describe_do_not_require_package_resolution tests.test_asterion_cli.AsterionCliTests.test_dci_run_without_transitional_package_fails_before_runtime tests.test_asterion_cli.AsterionCliTests.test_dci_run_accepts_explicit_transitional_package_injection` initially failed because DCI provider list/describe still required unresolved package composition, explicit package injection was not accepted by `main`, and only the no-package pre-runtime failure path already failed closed.

Transition design:
- `dci-agent-lite` now publishes exact `CapabilityPackageRef("dci", "1.0.0")` metadata only; it does not import DCI implementations during provider load.
- Generic CLI run composition accepts explicitly injected `InstalledCapabilityPackage` values and falls back only to registered built-in sources for missing refs, so DCI stays unregistered and unavailable without host injection.
- The DCI product verifier constructs a DCI-owned transitional local-directory package only inside the DCI verification boundary, preserving Task 6's future adapter direction without adding generic directory scanning.
- Package implementation bindings may exceed one selected assembly's executable closure, but runtime execution exposes only the executable refs required by the composed assembly.

GREEN:
- `uv run python -m unittest -v ...focused 63-test command...` -> 63 tests OK.
- `uv run pyright src/asterion/applications/dci_agent_lite/provider.py src/asterion/applications/provider.py src/asterion/cli.py` -> 0 errors.
- `uv run pyright --outputjson ...touched files...` compared against `c708053` archive baseline -> baseline 60 errors, current 39 errors, new unique errors 0.
- `uv run ruff check src/asterion/applications/dci_agent_lite/provider.py src/asterion/applications/provider.py src/asterion/cli.py src/asterion/dci/verification.py tests/test_asterion_cli.py tests/test_dci_complete_application.py` -> all checks passed.
- `uv run python -m compileall -q src/asterion tests/test_asterion_cli.py tests/test_dci_complete_application.py` -> PASS.
- `git diff --check` -> PASS.

Concerns:
- Broad `make check` was intentionally not run per current instruction.

## Minor Injection Exactness Fix

Status: PASS

RED:
- `uv run python -m unittest -v tests.test_asterion_cli.AsterionCliTests.test_extra_capability_package_injection_fails_before_runtime` initially failed because an unused but valid injected package was silently ignored instead of rejected.

GREEN:
- `uv run python -m unittest -v tests.test_asterion_cli.AsterionCliTests.test_dci_list_provider_and_describe_do_not_require_package_resolution tests.test_asterion_cli.AsterionCliTests.test_dci_run_without_transitional_package_fails_before_runtime tests.test_asterion_cli.AsterionCliTests.test_dci_run_accepts_explicit_transitional_package_injection tests.test_asterion_cli.AsterionCliTests.test_extra_capability_package_injection_fails_before_runtime tests.test_builtin_capability_source tests.test_installed_application_provider tests.test_builtin_controlled_code_application` -> 24 tests OK.
- `uv run pyright src/asterion/applications/dci_agent_lite/provider.py src/asterion/applications/provider.py src/asterion/cli.py` -> 0 errors.
- `uv run ruff check src/asterion/cli.py tests/test_asterion_cli.py` -> all checks passed.
- `git diff --check` -> PASS.

Design:
- Injected package refs must be a subset of the selected provider's exact required package refs.
- Malformed injected package identities and normal hash/equality failures are converted to the same context-free `ApplicationProviderError`; `BaseException` remains uncaught.
