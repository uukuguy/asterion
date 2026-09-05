# Task 1: Prime P1 authority artifact lock

## Implementation

- Added a fixed, canonical packaged descriptor for exactly the eleven P1 authority Python artifacts and the installed `asterion` distribution version.
- Added descriptor-relative, no-follow bounded reads. Each artifact must be a single-link regular file without group/world write permission, retain the same identity across the read, and match its SHA-256 via constant-time comparison.
- Added an opaque, idempotently closeable artifact admission token. The production aggregate acquires it before all other resources and closes it last, including failure cleanup.
- This work does not introduce readiness, probing, execution, networking, Docker invocation, subprocesses, LLM behavior, or native Docker qualification.

## TDD evidence

### RED

Command:

```sh
uv run python -m unittest -v tests.test_prime_p1_authority_artifact_lock tests.test_prime_p1_authority_resources
```

Result: failed as expected before implementation. Both test modules reported `ModuleNotFoundError: No module named 'asterion.applications.prime_agent.operator.authority_artifact_lock'`.

### GREEN

Command:

```sh
uv run python -m unittest -v tests.test_prime_p1_authority_artifact_lock tests.test_prime_p1_authority_resources tests.test_prime_p1_authority_process tests.test_prime_p1_authority_docker_socket
```

Result: `Ran 85 tests ... OK (skipped=2)`. The two skips are existing platform-specific Linux SCM_RIGHTS/atomic socket-flag skips.

Static checks:

```sh
uv run ruff check src/asterion/applications/prime_agent/operator/authority_artifact_lock.py src/asterion/applications/prime_agent/operator/authority_resources.py tests/test_prime_p1_authority_artifact_lock.py tests/test_prime_p1_authority_resources.py
git diff --check
```

Result: `All checks passed!`; `git diff --check` exited 0.

## Remaining risk

The descriptor hashes the current source-tree artifacts. Packaging/distribution coverage is a separate promotion-check concern and is not claimed by this task.

## P1 authority artifact lock hardening follow-up

### RED

Command:

```sh
uv run python -m unittest -v tests.test_prime_p1_authority_artifact_lock
```

Result: failed as expected before the follow-up implementation (`Ran 4 tests in 1.021s`, `FAILED (failures=2)`). `test_rejects_leaf_fifo_without_waiting_for_a_writer` timed out because leaf `os.open` waited for a FIFO writer; `test_rejects_artifact_linked_during_read` failed because adding a hard link during the read did not cause rejection.

### GREEN

Command:

```sh
uv run python -m unittest -v tests.test_prime_p1_authority_artifact_lock
```

Result: `Ran 4 tests in 0.140s`, `OK`. The suite includes the full packaged admission assertion, prompt FIFO rejection, and rejection of a hard link introduced during the read.

Static checks:

```sh
uv run ruff check src/asterion/applications/prime_agent/operator/authority_artifact_lock.py tests/test_prime_p1_authority_artifact_lock.py
git diff --check
```

Result: `All checks passed!`; `git diff --check` exited 0.
