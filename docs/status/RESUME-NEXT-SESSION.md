# Live Session Checkpoint

> Updated: 2026-09-04 13:25. **Session remains active — not a final handoff.**

## TL;DR

- P1–P7 retain provider-free acceptance implementations; real Docker/model/
  network/benchmark/ARC evidence remains External-limited.
- P4–P7 now also have sealed restricted-worker facades. P4 has canonical
  diagnostic completion and cancellation-safe cleanup; P5/P6/P7 have strict,
  scenario-specific canonical completions that reject forged traces.
- P7 adds a source-lock-preflighted, inert injected-engine factory. It permits
  only the fixed one-game ARC adapter at exactly 300 seconds and 4096 bytes.
- Cross-scenario isolation passed: every P4–P7 foreign role/workload pair is
  rejected before launch. P4 and P7 independent reviews passed.

## Current decision

- Prime is an IPython-only action surface with recursive `rlm(...)` and a
  versioned Continual Harness—not generic Native/DCI parity.
- Provider-free tests validate causal ordering and rejection boundaries only;
  they never promote an external runtime claim.

## Verification evidence

- Focused P4–P7 worker, acceptance, trace, live-reducer, gate, and integration
  suites passed; scoped Ruff, Pyright, and `git diff --check` passed.
- A new whole-repository `make test` attempt was stopped after a non-Prime
  hard-link loop exceeded 14 minutes. A new `make promotion-check` attempt was
  stopped after its proxy-backed `npm ci` stalled. Both are **Not rerun**, not
  PASS or FAIL.
- Earlier clean repository evidence remains historical only: promotion passed
  before the new worker facade commits; it does not verify this head.

## Immediate next action

1. Diagnose/bound the unrelated full-suite hard-link loop before claiming a new
   repository-wide test PASS.
2. Retry promotion only after npm's local proxy path is responsive; retain its
   result as Not rerun until an exit code and output are captured.
3. Keep real Prime worker/model/ARC runs External-limited absent a separately
   scoped operator authorization.

## Recovery commands

```bash
git status --short
git log --oneline -16
uv run python -m unittest -v tests.test_prime_restricted_scenario_worker tests.test_prime_restricted_scenario_worker_integration tests.test_prime_diagnostic_session_recovery_worker tests.test_prime_bounded_autonomy_worker tests.test_prime_continual_improvement_worker tests.test_prime_arc_agi_3_worker tests.test_prime_application_provider tests.test_prime_worker_gate
make promotion-check
```
