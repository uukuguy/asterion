# Task 2 Report: Add the standard Native entry

## What you implemented

Added the one package-uniform library entry, `prepare_native_application`, and the provider-free prepare/run tests. There is no example script and no live model run.

`prepare_native_application(spec, operator)` loads the existing `native` provider, resolves it with the operator's runtime factories and the built-in `dci` and `controlled-code` packages, and selects `application_id@version`. It returns a `NativeApplication` only when that application has exactly one assembly and the operator's host-service option keys and managed keys are disjoint and together equal the assembly's host capabilities. Missing applications, wrong versions, an empty runtime registry, and mismatched host-service keys raise `NativeApplicationError` with no chained cause. Preparation does not call the runtime factory.

`NativeApplication.run(input_text, *, run_id, signal=None)` is single-use. A cancelled signal fails before `HostServiceFactoryRegistry.open` and before the runtime factory, and still consumes the application. A successful or failed first run blocks a second run. The run opens host services for `plan.host_capabilities`, constructs the runtime with empty `host_services` and the operator's runtime options, and returns `run_composed_application`. It does not store the runtime, call `close`, branch on `application_id`, or branch on a host capability id.

`NativeApplication.capability_packages` exposes the selected application's package refs. `native.packages` remains the first provider application and its assembly file was not edited.

## What you tested and the test results

Command:

```bash
uv run python -m unittest -v tests.test_native_application tests.test_native_package_host
```

Result: `Ran 11 tests in 0.412s` / `OK`.

Covered behavior:

- Entry sources do not contain `asterion.capabilities.dci`, `asterion.capabilities.controlled_code`, `PiChildProcess`, `load_dotenv`, `.env`, or the contiguous string `run_application`. `application.py` calls `run_composed_application`.
- `native.dci-research` prepares without calling the runtime factory, exposes only `dci@1.0.0`, then runs one retrieval. The factory context is `native` / `native.dci-research@1.0.0` with empty host services and no `cwd_host_capability`. The corpus root is opened once. The runtime sees the question and `filesystem.read`. The result includes `research.completed` and `application/vnd.dci.research+json`.
- Relative and missing corpus roots raise `HostServiceRegistryError` before the runtime factory, then a second run raises `NativeApplicationError`.
- A cancelled DCI or controlled-code run fails before open and blocks a second run.
- A second DCI run fails after one successful run, with one factory call.
- `native.controlled-code` uses the managed `executor.controlled` service, does not call the runtime `run` method, and emits the code-quality workflow and audit events plus both code-quality media types.
- `native.packages` accepts both host services and exposes `controlled-code@1.0.0` then `dci@1.0.0` without opening the executor or calling the factory. Partial keys, overlapping keys, an unknown id, version `9.9.9`, and an empty runtime registry fail closed.
- Existing `tests.test_native_package_host` still passes.

## TDD evidence

RED, before the entry existed:

```bash
uv run python -m unittest -v tests.test_native_application
```

```text
ERROR: test_dci_research_runs_one_retrieval_without_preparing_the_runtime
...
ModuleNotFoundError: No module named 'asterion.agents.native'
...
Ran 8 tests in 0.006s
FAILED (errors=8)
```

Every test failed in `setUp` on `from asterion.agents.native.application import ...`. That failure was expected: the test was added before `src/asterion/agents/native/` existed.

GREEN, after `src/asterion/agents/native/__init__.py` and `application.py`:

```bash
uv run python -m unittest -v tests.test_native_application tests.test_native_package_host
```

```text
test_cancelled_controlled_code_run_fails_before_open ... ok
test_cancelled_dci_run_fails_before_open_and_blocks_a_second_run ... ok
test_controlled_code_uses_the_managed_executor ... ok
test_dci_research_runs_one_retrieval_without_preparing_the_runtime ... ok
test_entry_source_does_not_import_package_implementations ... ok
test_host_service_keys_must_match_the_selected_assembly ... ok
test_relative_and_missing_corpus_fail_before_the_runtime_factory ... ok
test_second_dci_run_fails ... ok
test_base_does_not_import_either_package ... ok
test_provider_free_assembly_resolves_both_packages_on_pi_reference ... ok
test_single_package_applications_register_beside_native_packages ... ok

Ran 11 tests in 0.412s

OK
```

## Files changed

Commit `4d9bdf93` on `native-dci-research-example`: `feat: add the native application entry`

- `tests/test_native_application.py` (created)
- `src/asterion/agents/native/__init__.py` (created)
- `src/asterion/agents/native/application.py` (created)

Not changed: `src/asterion/agents/__init__.py`, `src/asterion/applications/native/`, `pyproject.toml`, status docs, and the rest of the tree. `git status --short` is empty. The commit was not pushed.

## Self-review findings

- The implementation is the brief's entry, including the second import of `resolve_installed_provider` from `asterion.applications.provider`. That split is redundant but required by the brief and does not change behavior.
- `prepare_native_application` resolves every application on the provider, then selects one. It does not branch on application id. The `filesystem.read`-only test factory is enough for all three assemblies, which the passing prepare and run tests confirm.
- Host-service matching uses set intersection and union against `plan.host_capabilities`. The overlap, missing-key, and exact-key cases in the test pass.
- The runtime is created only inside `run`, with `host_services={}`, and is not stored. Cancellation and the consumed flag are checked before `open`.
- Source checks pass for the new entry and the existing provider: no package-implementation imports, no `PiChildProcess`, no `load_dotenv`, no `.env`, and no contiguous `run_application`.
- No second Pi runner, no change to `prepare_prime_application`, no CLI, no `asterion.application_index` row, and no `executor.controlled` entry point.
- Tests assert the public contract rather than a private helper. No extra files or product behavior were added.

## Issues or concerns

None. The brief's verification command passed. The whole repository suite was not run, by instruction.
