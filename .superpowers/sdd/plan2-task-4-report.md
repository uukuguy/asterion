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
