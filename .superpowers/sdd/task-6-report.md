# Task 6 report — native P7 broker and replay

## Delivered

- Added `ArcBroker` for the fixed `ls20-9607627b` game, seed `0`, and a
  500-dispatched-primitive-action ceiling.
- Validated full action batches before dispatch, journaled immutable
  before/after state digests with contiguous primitive sequences, and stopped
  immediately at the first level transition.
- Closed the authority after terminal transition, cap exhaustion, invalid
  engine output, or a post-dispatch exception.  The latter is recorded as
  `engine-uncertain` and is not replayable.
- Added a fresh-engine replay verifier that requires exact digest transitions,
  terminal level count, fixed identity, and receipt digest agreement.
- Kept receipt evidence content-safe: it includes hashes and public metadata,
  never frames, observations, prompts, provider values, or source paths.

## Evidence

- RED: `uv run python -m unittest -v tests.test_prime_p7_native_broker tests.test_prime_p7_native_replay` failed before implementation because both native modules were absent.
- GREEN: `uv run python -m unittest -v tests.test_prime_p7_native_broker tests.test_prime_p7_native_replay tests.test_prime_p7_solving_broker tests.test_prime_p7_solving_score` — 23 tests passed.
- `uv run ruff check` on all Task 6 source/tests — passed.
- `uv run python -m py_compile` on Task 6 source — passed.
- `uv run pyright` on Task 6 source/tests — 0 errors, 0 warnings.
- `git diff --check` — passed.

## Boundary

This establishes plumbing and deterministic replay only.  The tests use a
controlled ARC-shaped engine and do not solve the public level; known action
traces remain replay/plumbing evidence, not acceptance evidence.
