# Task 4 report: one-question live preset

## What I implemented

Added the provider-free live preset around the existing `run_native_dci_research` helper and `QUESTION`.

- `examples/applications/native_dci.py` now defines `ReadinessFailure`, `LiveConfiguration`, `resolve_live_configuration`, `live_runtime_options`, `execute_live`, `run_live`, and `main`. Live imports sit at the top of the file. There is no second top-level import block. `load_dotenv` is called only from `main`, with `override=False`. The helper and `QUESTION` are unchanged. The live command does not construct `PiChildProcess`.
- `examples/native_dci_example.sh` is mode `0755` and only execs `uv run python examples/applications/native_dci.py --live`.
- `Makefile` adds `native-dci-example` to the existing `dci-basic-example` `.PHONY` line and a tab recipe, `bash examples/native_dci_example.sh`. It is not attached to `verify.native-verified-loop.small`.
- `tests/test_native_application.py` gained `NativeDciLivePresetTests`.
- `docs/status/INDEX.md` and `docs/status/JOURNAL.md` record the readiness stop.

Live options are `tools=read,grep`, `max_turns=6`, and `cwd` set to the corpus. They do not pass `cwd_host_capability`, `bash`, `rg`, or a thinking level. Stdout on a run is one body-free JSON object. A readiness failure prints only the public reason and exits 2.

## What I tested

RED, before the implementation:

`uv run python -m unittest -v tests.test_native_application.NativeDciLivePresetTests`

Result: `FAILED (errors=4)`.

- `test_shell_and_makefile_are_thin`: `FileNotFoundError` for `examples/native_dci_example.sh`.
- `test_missing_provider_does_not_call_prepare`: `AttributeError: module 'native_dci_live' has no attribute 'run_live'`.
- `test_runtime_failure_is_body_free_and_hides_the_exception`: `AttributeError` for `LiveConfiguration`.
- `test_ready_configuration_matches_the_factory_path_rule`: `AttributeError` for `resolve_live_configuration`.

That failure was expected. The shell, Make target, and live helpers did not exist yet.

GREEN, after the implementation:

`uv run python -m unittest -v tests.test_native_application tests.test_native_package_host`

Result: `Ran 16 tests in 0.496s` / `OK`.

`uv run python -c "import runpy; runpy.run_path('tools/check_promotion.py', run_name='promotion_path_check')"`

Result: exit 0. That `run_name` does not enter `main()`, so this invocation does not execute the promotion audit. The brief asked for this command and exit 0.

The provider-free tests do not call a model.

## Live command

Command, run once: `make native-dci-example`

Exit code: 2

Public reason: `pi checkout is unavailable`

Stdout was only Make's recipe echo. Stderr was the public reason plus Make's error wrapper. No JSON status line. The model was not called. The command was not run again.

Before the run, local symlinks were created and not committed:

- worktree `.env` → primary checkout `.env`
- worktree `pi` → primary checkout `pi`

`/pi/` in `.gitignore` does not match a symlink, so `/pi` was added to the local common `.git/info/exclude`. After that, `git status --short` does not list `.env` or `pi`.

## Files changed

Commit `b8069cc3` `feat: add the native dci live preset` on `native-dci-research-example`:

- `examples/applications/native_dci.py`
- `examples/native_dci_example.sh` (100755)
- `Makefile`
- `tests/test_native_application.py`
- `docs/status/INDEX.md`
- `docs/status/JOURNAL.md`

Not committed: `outputs/`, `.env`, `pi`, and the local exclude file. Nothing was pushed.

## Self-review

- The preset matches the brief: public readiness reasons, body-free failure JSON, hidden exception text, exact factory path rejection for symlinks, and a thin shell.
- `run_native_dci_research` still calls `prepare_native_application` and does not read `.env` or spawn Pi.
- Names and file layout match the brief. No second example script and no Native CLI, registry row, or `pyproject.toml` change.
- Tests cover the thin shell, missing provider, redacted runtime failure, and the path rule, including the symlink corpus and evidence-parent cases.

## Issues and concerns

- `from __future__ import annotations` was removed from `examples/applications/native_dci.py`. On Python 3.14, a frozen dataclass with postponed annotations crashes when the tests load the file through `spec_from_file_location` without inserting the module into `sys.modules` (`sys.modules.get(cls.__module__)` is `None`). Removing the future import keeps the brief's dataclass and the brief's loaders working. Runtime behavior of the helper is unchanged.
- `python-dotenv` is only an optional extra. This worktree's `.venv` did not have it, so it was installed locally with `uv pip install` and was not committed. A clean `uv run` without that package raises `ModuleNotFoundError` at import, before readiness. The focused test command and the shell both use plain `uv run`.
- The required `pi` symlink cannot satisfy `_real_directory`, which rejects symlinks. The one live run stopped at `pi checkout is unavailable`. That is a completed readiness exit, not a second attempt. No corpus file was created.

## Fix: native dci make entry

The live command entry is the Makefile target `native-dci-example`. It now passes `--with "python-dotenv>=1.0.0"`, the same way Prime targets do, so the command does not depend on an optional extra already being installed. It does not use `--isolated`, a wheel build, ipython, or a guest machine. `examples/applications/native_dci.py` was not changed; the top-level `dotenv` import stays.

- `Makefile`: the `native-dci-example` recipe is a tab line, `$(UV_BIN) run --with "python-dotenv>=1.0.0" python examples/applications/native_dci.py --live`. It does not call the shell. The help line is `DCI bounded examples: dci-basic-example dci-runtime-context-example native-dci-example`. The target is not attached to `verify.native-verified-loop.small`.
- `examples/native_dci_example.sh`: kept the shebang, `set -euo pipefail`, and the existing `cd` to the repo root. It does not `source` anything and does not `set -a`. The exec line is `exec uv run --with "python-dotenv>=1.0.0" python examples/applications/native_dci.py --live`.
- `tests/test_native_application.py`: `test_shell_and_makefile_are_thin` still checks the live script path, the absence of `source ` and `set -a`, the `\nnative-dci-example:\n` target, `load_dotenv` absent from the Native entry, `override=False`, and `PiChildProcess` absent from the example. It now asserts `--with "python-dotenv>=1.0.0"` in the shell and the `$(UV_BIN) run --with ...` recipe in the Makefile, instead of `bash examples/native_dci_example.sh`.

Commit `929e83a3` `fix: define the native dci make entry` on `native-dci-research-example`. Only those three files. Nothing was pushed. `make native-dci-example` was not run.

Test command:

`uv run --with "python-dotenv>=1.0.0" python -m unittest -v tests.test_native_application tests.test_native_package_host`

Result: exit 0. `Ran 16 tests in 0.440s` / `OK`.

```
test_cancelled_controlled_code_run_fails_before_open ... ok
test_cancelled_dci_run_fails_before_open_and_blocks_a_second_run ... ok
test_controlled_code_uses_the_managed_executor ... ok
test_dci_research_runs_one_retrieval_without_preparing_the_runtime ... ok
test_entry_source_does_not_import_package_implementations ... ok
test_host_service_keys_must_match_the_selected_assembly ... ok
test_relative_and_missing_corpus_fail_before_the_runtime_factory ... ok
test_second_dci_run_fails ... ok
test_example_calls_the_standard_entry ... ok
test_missing_provider_does_not_call_prepare ... ok
test_ready_configuration_matches_the_factory_path_rule ... ok
test_runtime_failure_is_body_free_and_hides_the_exception ... ok
test_shell_and_makefile_are_thin ... ok
test_base_does_not_import_either_package ... ok
test_provider_free_assembly_resolves_both_packages_on_pi_reference ... ok
test_single_package_applications_register_beside_native_packages ... ok

Ran 16 tests in 0.440s

OK
```
