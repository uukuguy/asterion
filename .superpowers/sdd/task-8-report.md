# Task 8 report: coordinate the bounded DCI coverage experiment

## Result

Implemented the provider-free `asterion-dci pathlight experiment prepare`,
authorized foreground `execute`, and read-only `status` commands.

`prepare` resolves the five canonical local dataset/corpus pairs through
`load_operator_config`, generates five private 10-case coverage registries,
writes one exact DCI capability source lock, and publishes an immutable
`pathlight-coverage-experiment.json`. The plan is non-executable and binds the
diagnosis, coverage proposal, case scope, sole variant, registry set, source
lock, 50 Agent operations, a 5,000,000 microusd cap, and the two-infrastructure-
failure stop rule.

`execute` accepts only a separate canonical 0600 authorization document bound
to those exact digests and limits. It validates the source lock, all five
registry/manifest/corpus closures, and all five benchmark drafts before the
first provider load. Execution is sequential and foreground-only. Each task
uses `case_limit=10`, a one-dollar share of the five-dollar envelope, and the
coverage registry path that selects the existing no-Judge IR branch.
`RealDciBenchmarkExecutor` now turns that exact coverage case into a bounded
full-execution authority for the first ten selected IDs: ten Agent operations,
zero Judge operations, and at most one dollar. Missing, non-positive, or
over-one-dollar coverage amounts fail before the Agent runner. Ordinary
non-coverage executions of 50 or fewer cases retain their prior behavior.

Immutable receipts bind every attempt to the plan, proposal, scope, variant,
registry, authorization, run ID, and generation. Re-entry skips completed
tasks. Failed or cancelled terminal benchmark runs start a new receipt/run
generation because the existing evidence store treats their run IDs as
terminal. Receipts additionally bind the authorized cost and either actual
consumption or a conservative upper bound. Resume authorizes only the
remaining per-task balance; missing or invalid cost evidence consumes the
whole prior authorization fail-closed. Two infrastructure failures stop
execution before a third task can launch. Completed authorization replay
fails closed.

All prepare outputs use one private staged tree with exclusive hard-link
publication and device/inode-proven rollback. Execution receipts reuse the
same validated flat private staging/publication primitive. Status reads only
the plan and immutable receipt chain and emits content-free counts, caps,
states, and digests.

## TDD evidence

The first focused run failed two tests because the `experiment` route was
absent. After the initial implementation those tests passed. The matrix was
then expanded and driven green for:

- exact five-by-ten scope, 50 operations, 5,000,000 microusd, and five exact
  instance selectors;
- provider-free prepare and fixed context-free stderr;
- missing, malformed, non-0600, cross-swapped, and repeated authority/plan
  inputs;
- missing registry roots before provider execution;
- five complete preflights before any provider load;
- sequential completion, completed replay rejection, cancellation, new
  digest-bound generation resume, first/second infrastructure failure, and
  third-task suppression;
- exact case-10 coverage authority, missing/zero/over-one-dollar rejection,
  body-free cost evidence, and a 250,000-microusd cancellation followed by an
  exact 750,000-microusd resumed authorization;
- private `.env` sentinel redaction, prepare rollback/retry, and read-only
  status.

No provider, Agent, Judge, model, or network operation ran during Task 8.

## Verification

```text
uv run python -m unittest -v \
  tests.test_dci_pathlight_experiment_cli \
  tests.test_dci_pathlight_cli \
  tests.test_dci_benchmark_host \
  tests.test_dci_benchmark_authorization
  PASS: 22 tests

uv run python -m unittest -v \
  tests.test_dci_pathlight_coverage \
  tests.test_dci_operator_inputs \
  tests.test_dci_benchmark_real_executor \
  tests.test_asterion_dci_benchmark
  PASS: 83 tests

uv run pyright \
  src/asterion/applications/dci_agent_lite/benchmark_executor.py \
  src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py \
  tests/test_dci_benchmark_real_executor.py \
  tests/test_dci_pathlight_experiment_cli.py
  PASS: 0 errors, 0 warnings

uv run ruff check \
  src/asterion/applications/dci_agent_lite/benchmark_executor.py \
  src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py \
  src/asterion/applications/dci_agent_lite/pathlight_cli.py \
  tests/test_dci_benchmark_real_executor.py \
  tests/test_dci_pathlight_experiment_cli.py
  PASS

git diff --check
  PASS
```

## Files

- `src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py`
- `src/asterion/applications/dci_agent_lite/benchmark_executor.py`
- `src/asterion/applications/dci_agent_lite/cli.py`
- `src/asterion/applications/dci_agent_lite/pathlight_cli.py`
- `src/asterion/capabilities/dci/implementation/pathlight/coverage.py`
- `tests/test_dci_pathlight_experiment_cli.py`
- `tests/test_dci_benchmark_real_executor.py`
- `.superpowers/sdd/task-8-report.md`

The pre-existing dirty `docs/status/JOURNAL.md` and
`docs/status/RESUME-NEXT-SESSION.md` were not edited or staged by this task.
