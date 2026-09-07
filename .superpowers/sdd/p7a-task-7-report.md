# P7a Task 7 report

Status: DONE

Baseline: `9c1a2873c4cef9b096c917a765cf05e1d9c58f83`.

## Delivered

- Added the source-locked, game-agnostic P7 solving prompt. Its private guidance lock binds the upstream commit, MIT license digest, and canonical prompt digest without placing prompt text in manifests or receipts.
- Added the one-prompt lifecycle joining the Task 4 broker, Task 5 persistent worker, and Task 6 gateway/provider. Broker seal state is the only level-completion authority; assistant prose cannot complete the run, and a tool callback observed after the solved latch returns without executing another worker cell.
- Finalization requires provider usage and callback counts to agree with the gateway terminal witness, followed by exact broker seal/replay agreement and validated local presentation.
- Cleanup always attempts gateway, provider, worker, and broker in that order. Cancellation and an existing public lifecycle error retain precedence over cleanup errors. A receipt is created and published only after successful cleanup.
- Reused the sole Task 3 `PrimeArcAgi3SolveReceipt` type. The one-run in-memory store validates the canonical non-circular receipt digest, keys by exact `(run_id, receipt_sha256)`, and consumes the exact retrieval once.
- Added an immutable private presentation contract and renderer. It validates exact fields, bounded rectangular grids, colors, action syntax, counts, score, and terminal state before writing any record through the injected `HostPresentationSink`. Presentation text never enters progress or the receipt.
- Progress records are phase-only `HostProgressEvent` values with no `current` or `total` counters.

## Reduced TDD coverage

Per the competition-development instruction, Task 7 contains exactly four aggregate scenarios:

1. Prompt/guidance lock and absence of fixed answers, action names, game IDs, or private paths.
2. Successful lifecycle with six dynamic primitive actions, authoritative `LEVEL_SOLVED`, quiescent stop, finalize/witness, seal/replay, presentation, ordered cleanup, one-time receipt publication, and no post-solve worker execution.
3. Callback limit, deadline, action cap, noncompletion, cancellation, and no automatic retry in one failure aggregate.
4. Original-error preservation across all cleanup failures plus renderer/receipt validation and redaction in one aggregate.

RED was observed first: all four scenarios failed with `ModuleNotFoundError` for the three missing Task 7 modules.

## Verification

- `uv run python -m unittest -v tests.test_prime_p7_solving_prompt tests.test_prime_arc_agi_3_solver_package tests.test_prime_p7_solving_renderer tests.test_prime_p7_solving_host`
- `uv run ruff check` over the three production modules and three focused test modules.
- `uv run pyright` over the three production modules.
- `git diff --check` over the Task 7 paths.

All verification is provider-free; no model or game action was started.
