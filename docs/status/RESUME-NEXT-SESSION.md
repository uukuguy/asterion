# Live Session Checkpoint

> Updated: 2026-09-04 08:50. **Session remains active — not a final handoff.**

## TL;DR

- P1–P7 have provider-free acceptance implementations. None has real
  Docker/model/network/benchmark/ARC execution evidence; such results remain
  External-limited.
- The repaired Prime source lock and installed-wheel resource closure now pass
  `make promotion-check`: 28 provider-free commands, zero provider operations,
  and no full dataset.
- P6 implements the fixed task-A → one candidate revision → task-B
  preserve-or-exact-rollback product over `HarnessCoordinator`; `e372297`
  binds scope, worker result, lock, task-B attestation, quiescence, cleanup,
  and global-scope approval before bounded evidence issuance.
- P7 implements a one-game IPython-only ARC-AGI-3 broker trace, injected host
  score replay, provider-free acceptance, and separate subset/full evidence
  reducers. `5f11dc5` never starts a worker or game; full evidence needs an
  exact finite operator authorization and remains unclaimed.

## Current decision

- Prime is an IPython-only action surface with recursive `rlm(...)` and a
  versioned Continual Harness—not generic Native/DCI parity.
- Provider-free tests validate causal ordering and rejection boundaries only;
  they never promote an external runtime claim.

## Verification evidence

- Focused P7 verification passed: 26 tests across workload, redacted trace,
  broker, acceptance, live reducers, worker gate, and evidence contract;
  scoped Ruff, Pyright, and `git diff --check` passed.
- Repository-wide provider-free `make test` passed (2,897 tests). It rebuilt
  pinned local Node fixtures but started no model, Docker, game, provider, or
  network operation.
- The full isolated `make promotion-check` passed after aligning one stale
  gateway test with the established sparse native-cursor contract.

## Immediate next action

1. Retain all external Prime evidence as External-limited.
2. Do not run a real ARC-AGI-3 suite without separately scoped authorization.
3. Continue only with provider-free implementation or review work unless an
   operator separately authorizes a finite real worker/model/benchmark run.

## Recovery commands

```bash
git status --short
git log --oneline -12
test -f /tmp/asterion-final-make-test.status && cat /tmp/asterion-final-make-test.status
tail -n 40 /tmp/asterion-final-make-test.log
uv run python -m unittest -v tests.test_prime_arc_agi_3_workload tests.test_prime_arc_agi_3_receipt tests.test_prime_arc_agi_3_broker tests.test_prime_arc_agi_3_acceptance tests.test_prime_arc_agi_3_live_validation tests.test_prime_worker_gate tests.test_prime_capability_evidence
make promotion-check
```
