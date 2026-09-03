# Live Session Checkpoint

> Updated: 2026-09-03 13:08. **Session remains active — not a final handoff.**

## TL;DR

- The P1 workload-result specification is committed at `23457b7`; Task 1 is
  committed at `1fd2ad8`, admitting only its fixed IPython fixture digest and
  binding receipts to redacted immutable completion bytes.
- The final review correction is committed at `f61a55b`: P5/P6 cannot issue
  bounded evidence until role-specific real launchers exist.
- Products 2–7 remain External-limited. Existing P2/P3 provider-free work and
  trusted-local P5 probe are non-promotable mechanics, not sandboxed PASS.
- P2's sealed acceptance coordinator is covered by a provider-free fake chain.
  It requires attestation, broker admission/release/revocation, result,
  destruction, boundary admission, and bounded reduction in that order; this
  is not Docker, model, or network execution and does not change P2's
  External-limited live-execution status.
- P3's sealed recursive-review acceptance coordinator now drives the fake
  worker/broker lifecycle through attestation, root admission, one relay,
  canonical completion, revoke, destruction, and cleanup.  It emits only a
  provider-free receipt; live P3 evidence requires explicit authorization and
  a real RLM/IPython observation.

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
- P2 acceptance: 56 focused P2/worker/broker Python tests and 63 P1
  cross-role regressions passed on main, with scoped Ruff, Pyright, and diff checks.
  These are provider-free fake-service checks only; no Docker daemon, model
  provider, or network action occurred.
- Review correction: an open network, persistent workspace, or inherited
  credential profile now rejects in coordinator preflight before worker or
  broker admission; 34 focused acceptance/profile/gate/worker tests passed.
- `make promotion-check` remains **not PASS** (stopped before unapproved
  Climb H-001); `make test` remains red on a pre-existing DCI packaged-
  assembly inventory expectation.

## Immediate next action

1. Complete P3 recursive-workflow acceptance review and integrate it on main;
   preserve the fixed IPython-only action surface and sealed P1/P2/P3 roles.
2. Retain P2/P3 live execution and P4–P7 as External-limited; ARC-AGI-3 remains
   unimplemented and requires a later isolated broker/functional-subset design.

## Recovery commands

```bash
git status --short
git log --oneline -12
make test.prime-long-running.provider-free
uv run python -m unittest -v tests.test_prime_bounded_autonomy_receipt
node --test packages/typescript/prime-gateway/test/main.test.mjs
```
