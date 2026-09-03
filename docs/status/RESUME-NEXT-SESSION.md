# Live Session Checkpoint

> Updated: 2026-09-03 12:20. **Session remains active — not a final handoff.**

## TL;DR

- The P1 workload-result specification is committed at `23457b7`. It selects
  one code-owned `prime.ipython-coding/v1` fixture by exact digest and requires
  a canonical, workload-bound worker result.
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

- Worker platform: 69 focused Python tests across shared lifecycle, seven-role
  gate, Docker adapter/CLI, launch barrier, and model broker passed; Node
  launcher syntax, Ruff, Pyright, and diff checks passed. No Docker, model, or
  network action occurred.
- Node: 37 Prime gateway main tests passed, including zero-resource native RLM
  budget clamping and expiry rejection.
- Ruff, Pyright, Node syntax, and `git diff --check` passed.
- `make promotion-check` remains **not PASS** (stopped before unapproved
  Climb H-001); `make test` remains red on a pre-existing DCI packaged-
  assembly inventory expectation.

## Immediate next action

1. Obtain review of the committed P1 workload-result specification.
2. After review, write and approve an implementation plan before code changes.
3. Retain P2–P7 as External-limited; ARC-AGI-3 remains unimplemented and
   requires a later isolated broker/functional-subset design.

## Recovery commands

```bash
git status --short
git log --oneline -12
make test.prime-long-running.provider-free
uv run python -m unittest -v tests.test_prime_bounded_autonomy_receipt
node --test packages/typescript/prime-gateway/test/main.test.mjs
```
