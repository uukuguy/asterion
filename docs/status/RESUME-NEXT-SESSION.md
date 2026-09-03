# Live Session Checkpoint

> Updated: 2026-09-03 13:49. **Session remains active — not a final handoff.**

## TL;DR

- P1's fixed workload-result implementation is committed at `a9d6e72`. It
  selects one code-owned `prime.ipython-coding/v1` fixture by exact digest and
  requires a canonical, workload-bound worker result.
- Final P1 provider-free verification boundary: five focused suites passed
  (57 tests), along with Ruff, Pyright, launcher byte-compilation, and
  `git diff --check`. This is not Docker/model/network execution.
- The final review correction is committed at `f61a55b`: P5/P6 cannot issue
  bounded evidence until role-specific real launchers exist.
- Products 2–7 remain External-limited. Existing P2/P3 provider-free work and
  trusted-local P5 probe are non-promotable mechanics, not sandboxed PASS.

## Current decision

- Prime is an IPython-only action surface with recursive `rlm(...)` and a
  versioned Continual Harness—not generic Native/DCI parity.
- The P1 Docker worker stays fixed to one image-owned fixture. The application
  supplies no source text, command, prompt, path, or environment values.
- A terminal `completed` marker by itself is insufficient: the host must bind
  the canonical result bytes and exact fixture digest to the lease.
- P5/P6 remain unable to issue bounded evidence. Their future launchers must
  be role-specific and independently real.

## Verification evidence

- P1 fixed workload-result protocol is provider-free test-verified: 57 focused
  Python tests across the Docker worker/CLI, IPython launcher protocol, worker
  gate, and coding-fixture receipt passed. Ruff, Pyright, launcher
  byte-compilation, and `git diff --check` passed. Docker/model/network
  execution was not run and is not a PASS claim.
- Node: 37 Prime gateway main tests passed, including zero-resource native RLM
  budget clamping and expiry rejection.
- Ruff, Pyright, Node syntax, and `git diff --check` passed.
- `make promotion-check` remains **not PASS** (stopped before unapproved
  Climb H-001); `make test` remains red on a pre-existing DCI packaged-
  assembly inventory expectation.

## Immediate next action

1. Retain P2–P7 as External-limited; P5/P6 gained no bounded evidence.
   ARC-AGI-3 remains unimplemented and requires a later isolated
   broker/functional-subset design.

## Recovery commands

```bash
git status --short
git log --oneline -12
make test.prime-long-running.provider-free
uv run python -m unittest -v tests.test_prime_bounded_autonomy_receipt
node --test packages/typescript/prime-gateway/test/main.test.mjs
```
