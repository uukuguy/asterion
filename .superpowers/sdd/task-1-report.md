# Task 1 Report: Register the two single-package applications

## What you implemented

Registered two single-package Native assemblies beside the unchanged `native.packages@1.0.0`. Provider `native` now exposes applications in this order:

1. `native.packages@1.0.0`
2. `native.dci-research@1.0.0` — package `dci@1.0.0`, runtime `pi.reference`, host capability `corpus.local-root`, capabilities `dci.research` and `policy.local-corpus`
3. `native.controlled-code@1.0.0` — package `controlled-code@1.0.0`, runtime `pi.reference`, host capability `executor.controlled`, capabilities `evaluation.code-quality`, `observability.execution-audit`, `policy.controlled-code-check`, and `workflow.code-quality`

No Native entry module, example, CLI, provider discovery, central registry, or `asterion.application_index` row was added. `pyproject.toml` and `native-packages.json` were not edited. `create_provider` keeps its existing imports and does not import `asterion.capabilities.dci` or `asterion.capabilities.controlled_code`.

Promotion path expectations in `tools/check_promotion.py` now include the two new assembly files immediately after `native-packages.json`, both as `asterion.application-assembly/v1`.

## What you tested and the test results

- RED, before implementation: `uv run python -m unittest -v tests.test_native_package_host.NativePackageHostTests.test_single_package_applications_register_beside_native_packages` — FAIL (1 test, 0.003s).
- GREEN, after implementation: the same command — OK (1 test, 0.065s).
- `uv run python -m unittest -v tests.test_native_package_host` — OK (3 tests, 0.109s).
- `uv run python -c "import runpy; runpy.run_path('tools/check_promotion.py', run_name='promotion_path_check')"` — exit 0. This runs the module-level path-set assert and does not call npm.
- `make promotion-check` — exit 1 after the path-set assert. See concerns. Not treated as a product failure.

The full repository suite was not run.

## TDD evidence

### RED

Command:

```bash
uv run python -m unittest -v tests.test_native_package_host.NativePackageHostTests.test_single_package_applications_register_beside_native_packages
```

Relevant failing output:

```text
AssertionError: Tuples differ: (('na[20 chars].0'),) != (('na[20 chars].0'), ('native.dci-research', '1.0.0'), ('nati[25 chars].0'))

Second tuple contains 2 additional elements.
First extra element 1:
('native.dci-research', '1.0.0')

- (('native.packages', '1.0.0'),)
?                               -

+ (('native.packages', '1.0.0'),
+  ('native.dci-research', '1.0.0'),
+  ('native.controlled-code', '1.0.0'))

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)
```

This failure was expected. At that point `create_provider` still returned only `native.packages@1.0.0`. The brief predicted the application tuple `(('native.packages', '1.0.0'),)`.

The first attempt to run this command failed earlier, while creating `.venv`, because the editable build hook runs `npm run build` and `packages/typescript/asterion-prime-extension/node_modules` was absent. `npm ci --ignore-scripts` in that package directory fixed the environment. That install is gitignored and is not part of the commit. The RED assertion above is from the rerun after that install.

### GREEN

Same command after the assemblies, provider entries, and promotion paths:

```text
test_single_package_applications_register_beside_native_packages (tests.test_native_package_host.NativePackageHostTests.test_single_package_applications_register_beside_native_packages) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.065s

OK
```

Full module:

```text
test_base_does_not_import_either_package ... ok
test_provider_free_assembly_resolves_both_packages_on_pi_reference ... ok
test_single_package_applications_register_beside_native_packages ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.109s

OK
```

## Files changed

Commit `2b77c81` (`2b77c81f0c3e53990b00fe5dd913154cba125d96`), subject `feat: register native single-package applications`. Five files, 133 insertions, 1 deletion. Working tree clean after the commit. Not pushed.

- Created: `src/asterion/applications/native/assemblies/native-dci-research.json`
- Created: `src/asterion/applications/native/assemblies/native-controlled-code.json`
- Modified: `src/asterion/applications/native/provider.py`
- Modified: `tools/check_promotion.py`
- Modified: `tests/test_native_package_host.py`

## Self-review findings

- Completeness matches the brief: both assemblies, provider order with `native.packages` first, promotion paths, and the selection test. No extra entry point, runner, CLI, or live model path.
- Names and versions are the brief's values: `native.dci-research@1.0.0` and `native.controlled-code@1.0.0`.
- The new test checks behavior, not only file presence: application order, absence of new `asterion.application_index` names, resolved package refs, host capabilities, capability ids, runtime id, and forbidden imports in `provider.py`.
- Existing `native.packages` registration and `native-packages.json` are unchanged. `pyproject.toml` is unchanged, so `native.packages__1.0.0` remains the only Native application-index row.
- Provider imports were not expanded. The forbidden-import assertion passed.
- Assembly JSON follows the existing `native-packages.json` shape and the brief text, including trailing newlines.
- No correctness issues found in the committed diff.

## Issues or concerns

`make promotion-check` did not reach npm or a wheel comparison. The Makefile resolved `ASTERION_PRIME_NODE` with `npm exec --offline --yes --package=node@22`, which produced an empty path. The invoked command was:

```text
uv run python tools/check_promotion.py --npm-cache "" --node-executable ""
```

Result:

```text
promotion check failed: declared Node executable is invalid
make: *** [promotion-check] Error 1
```

That message comes from `_resolve_promotion_node_executable` in `main`, which runs only after the module-level path-set assert. The dedicated path-set command already exited 0, and this failure is not a symmetric difference of assembly paths. System `node` is v24.20.0 at `/opt/homebrew/bin/node`; the checker requires Node 22 (>= 22.15.0) and rejects symlinks, so the host Node would not satisfy the check even if passed through. No model was started. This is an environment limit, not a product failure.
