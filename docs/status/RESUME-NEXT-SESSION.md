# Live Session Checkpoint

> Updated: 2026-09-03 09:36. **Session remains active — not a final handoff.**

## TL;DR

- Smoke Core is closed as a narrow regression gate; it is not the Prime roadmap.
- The approved Prime program has seven end-to-end products through ARC-AGI-3.
- P1 source/worker, RLM, and continual-harness contracts are implemented, but
  `bounded-sandboxed` still requires a real native-Linux worker, exact offline
  image, host broker, and fixed coding scenario.
- Candidate release authority is platform-neutral: `linux/arm64` plus
  `linux/amd64`; the promoted catalog remains empty.
- Recent corrective work binds recipe identity, parser-produced private captures,
  public URL-free projections, descriptor-relative staging, and materialization
  plans. Python 3.11's real hash-pinned 33-package closure is committed at
  `aac16c1` and strictly read from package resources at `659e355`.

## Current decision

- Prime is an IPython-only action surface with recursive `rlm(...)` and a
  versioned Continual Harness—not generic Native/DCI parity.
- Python owns authority, budget, recovery, and evidence; TypeScript retains
  upstream kernel/session/RLM mechanisms. The pinned upstream checkout is
  read-only.
- Candidate specifications must become a complete per-target graph before any
  artifact is fetched. A lock alone is not materialized evidence or a promoted
  image lock.
- Docker Desktop/OrbStack evidence stays `External-limited`; supported-native
  claims require matching native Linux execution.

## In-flight constraints

- `prime_python_wheel_requirements()` parses only canonical hash-pinned lock
  syntax and returns all 33 exact project/version requirements. It performs no
  network or materialization.
- Candidate admission now requires the complete parser-backed graph: target Node
  archive/modules, OCI index-selected manifest/config/contiguous layers, all 33
  locked Python wheels, local runtime wheel, fixture, and frontend. The graph
  stays untrusted and contains no fetched or built artifact.
- Authorized descriptor-relative staging now also accepts only a matching
  private complete candidate request and exact artifact tuple before its first
  fetch. Its deterministic fixture successfully stages and rehashes 41 objects;
  no actual artifacts were acquired.
- The full P1 provider-free integration matrix passed 95 tests across worker,
  Docker adapter fakes, launcher, broker, fixed image, compatibility process,
  and coding receipt. It does not establish `bounded-sandboxed` evidence.
- `prime.programmatic-long-context/v1` now has a separate closed receipt
  contract. It can emit only `provider-free` PASS after exact IPython-only,
  digest/count, executed-program, and oracle facts; it cannot upgrade evidence.
- `make promotion-check` was stopped before it entered `tools/climb/cycle.sh
  H-001`; that path requires separate benchmark authority. It is **not PASS**.
  Focused recipe tests, Ruff, Pyright, and `git diff --check` passed for
  `659e355`.
- `make test` remains red on a pre-existing DCI packaged-assembly inventory
  expectation exposed by Prime installation; leave it unchanged unless
  separately authorized.

## Immediate next action

1. Commit the long-context receipt contract, then implement the real pinned
   Prime/IPython corpus compatibility fixture from its approved P2 plan.
2. Do not fetch, build, run Docker, promote an image, or invoke a provider.

## Recovery commands

```bash
git status --short
git log --oneline -12
uv run python -m unittest -v tests.test_prime_image_release_materializer tests.test_prime_release_metadata tests.test_prime_release_spec_generation tests.test_prime_release_recipe tests.test_prime_image_input_lock
uv run ruff check src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/prime_release_test_support.py tests/test_prime_image_release_materializer.py
uv run pyright src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/prime_release_test_support.py tests/test_prime_image_release_materializer.py
uv run python -m unittest -v tests.test_restricted_worker_service tests.test_bounded_model_session tests.test_prime_worker_gate tests.test_prime_docker_worker tests.test_prime_docker_cli tests.test_prime_launcher_barrier tests.test_prime_linux_probe tests.test_prime_model_broker tests.test_prime_coding_fixture_receipt tests.test_prime_ipython_image tests.test_prime_ipython_launcher_protocol tests.test_prime_ipython_coding_compat
uv run python -m unittest -v tests.test_prime_programmatic_long_context_receipt tests.test_prime_capability_evidence
```
