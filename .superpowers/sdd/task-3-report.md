# Task 3 Report: Add the provider-free DCI example

## What you implemented

Added the provider-free development example for `native.dci-research`. It does not start Pi, read `.env`, resolve an assembly itself, or call a model.

`examples/applications/native_dci.py` defines `QUESTION` and `run_native_dci_research(*, runtime_factories, runtime_options, corpus_root, question, run_id) -> ApplicationRunResult`. The helper builds `NativeApplicationSpec(application_id="native.dci-research", application_version="1.0.0")` and `NativeOperatorContext` with the caller-owned registry, the caller-owned runtime options, `host_service_options={"corpus.local-root": {"root": corpus_root}}`, and `managed_host_services={}`. It calls `prepare_native_application` and then `application.run(question, run_id=run_id)`.

`examples/README.md` keeps both existing paragraphs. After the first paragraph it now says that `applications/native_dci.py` runs the Native DCI retrieval application through `prepare_native_application`, and that the same entry runs every Native application.

`tests/test_native_application.py` gained `NativeDciExampleTests`, placed before the module `if __name__` guard so the class stays with the other module-level tests. The class body is the brief's test verbatim.

No live preset, shell script, Make target, model call, second example, or change to `dci_research.py` / `controlled_code.py` was added.

## What you tested and the test results

RED, before the example existed:

`uv run python -m unittest -v tests.test_native_application.NativeDciExampleTests`

Result: `FAILED (errors=1)` in 0.002s.

GREEN, after the example and README sentence:

`uv run python -m unittest -v tests.test_native_application tests.test_native_package_host`

Result: `Ran 12 tests in 0.400s` / `OK`. That includes `NativeDciExampleTests.test_example_calls_the_standard_entry` and the existing native application and package-host tests.

Extra self-review, not a brief verification command: `uv run ruff check tests/test_native_application.py examples/applications/native_dci.py` reported `All checks passed!`

## TDD evidence

RED command:

`uv run python -m unittest -v tests.test_native_application.NativeDciExampleTests`

Relevant failing output:

```
test_example_calls_the_standard_entry (tests.test_native_application.NativeDciExampleTests.test_example_calls_the_standard_entry) ... ERROR
...
File "/Users/sujiangwen/sandbox/agentic-2026/asterion/.worktrees/native-dci-research-example/tests/test_native_application.py", line 419, in test_example_calls_the_standard_entry
    spec.loader.exec_module(module)
...
FileNotFoundError: [Errno 2] No such file or directory: '/Users/sujiangwen/sandbox/agentic-2026/asterion/.worktrees/native-dci-research-example/examples/applications/native_dci.py'
----------------------------------------------------------------------
Ran 1 test in 0.002s

FAILED (errors=1)
```

That failure was expected. Step 2 of the brief says the test errors because `examples/applications/native_dci.py` is missing. `spec_from_file_location` still returns a loader, and `exec_module` then raises `FileNotFoundError`. No implementation was present yet.

GREEN command:

`uv run python -m unittest -v tests.test_native_application tests.test_native_package_host`

Relevant passing output:

```
test_example_calls_the_standard_entry (tests.test_native_application.NativeDciExampleTests.test_example_calls_the_standard_entry) ... ok
...
----------------------------------------------------------------------
Ran 12 tests in 0.400s

OK
```

The example test checks the helper source for the banned strings, the exact `QUESTION` text, one factory call with empty `host_services`, the passed question as runtime input, a `research.completed` event, and the three README phrases.

## Files changed

- `examples/applications/native_dci.py` (created)
- `examples/README.md` (one paragraph after the first)
- `tests/test_native_application.py` (`NativeDciExampleTests` appended before the main guard)

Commit: `bd4d8db4` `feat: add the native dci research example`

`git status --short` is empty after the commit. The commit was not pushed. Forbidden status files were not edited.

## Self-review findings

- Completeness: the example, README sentence, and test match the brief. The produced function signature and `QUESTION` constant match the interfaces section.
- The test was written and run before the example existed. The RED error is the missing file, not an assertion about unfinished behavior.
- Name clarity: `run_native_dci_research`, `QUESTION`, and `NativeDciExampleTests` are the brief's names. No extra helpers were added.
- YAGNI: no second script, live preset, shell wrapper, Make target, or model call.
- Existing pattern: the corpus option and empty managed map match `NativeApplicationTests.test_dci_research_runs_one_retrieval_without_preparing_the_runtime`. The example does not import package implementations, call `resolve_assembly`, or select `applications[0]`.
- The test verifies behavior, not only file presence: source bans, question identity, one runtime factory call, empty factory host services, input text, and `research.completed`.
- Class placement before `if __name__ == "__main__"` is the only structural choice. The class text is unchanged, and unittest loads it because it is module-level.

## Issues or concerns

None. The live factory, readiness exit, and `make native-dci-example` path remain for a later task and were not implemented here.
