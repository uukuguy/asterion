# Live Session Checkpoint

> Updated: 2026-09-03 10:20. **Session remains active — not a final handoff.**

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
- Python wheel closure is enforced, but do not claim the full graph: Node module,
  OCI config/manifest/layers, local runtime, fixture, and frontend remain to be
  required before candidate admission.
- `make promotion-check` was stopped before it entered `tools/climb/cycle.sh
  H-001`; that path requires separate benchmark authority. It is **not PASS**.
  Focused recipe tests, Ruff, Pyright, and `git diff --check` passed for
  `659e355`.
- `make test` remains red on a pre-existing DCI packaged-assembly inventory
  expectation exposed by Prime installation; leave it unchanged unless
  separately authorized.

## Immediate next action

1. Extend the closure to Node, OCI child config and all layers, local runtime,
   fixture, and frontend—without downloading bytes.
2. Only then request distinct authorization to fetch/verify target artifacts and
   later assemble an offline image. Do not build or run an image now.

## Recovery commands

```bash
git status --short
git log --oneline -12
uv run python -m unittest -v tests.test_prime_release_recipe
uv run ruff check src/asterion/applications/prime_agent/operator/release_recipe.py tests/test_prime_release_recipe.py
uv run pyright src/asterion/applications/prime_agent/operator/release_recipe.py tests/test_prime_release_recipe.py
```
