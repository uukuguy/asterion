# Prompt Operation Boundary Implementation Plan

> **For agentic workers:** Execute this bounded assignment inline using test-driven-development; the coordinating agent reviews and commits the result.

**Goal:** Resolve review R1/R6 without changing public v1 contracts or running a model.

**Architecture:** PiRpcSession owns exact request acknowledgment and the settlement barrier. Native agent cycles may continue before settlement; sent operations that fail remain fenced. Compact wire responses are validated before canonical event projection, independently of compact_events.

**Tech Stack:** Python asyncio/threaded JSONL subprocess transport, unittest, local fake Pi producer.

## Global Constraints

- One in-flight operation per session, absolute session deadline, no retry or rollback claim after dispatch.
- Settlement proves cessation, not successful model/tool/application work.
- Keep runtime domain neutral and public schemas unchanged.
- Parent agent owns final review and commit; no live provider execution.

## Task 1: Prompt boundary and Prime consumption

**Files:** `src/asterion/runtimes/pi_rpc.py`, `tests/test_pi_rpc_reusable.py`, `tests/test_pi_session.py`, `src/asterion/agents/prime/execution.py`, directly affected Prime fake producers.

- [x] Add a fake producer with exact-ID response, agent cycle, delayed settlement; run three sequential prompts for both compact settings. Assert each result ends at its own settlement, text matches its prompt, and sequences stay contiguous.
- [x] Add missing/wrong ack, error/aborted assistant, post-run continuation and cancellation regression cases. Run `uv run python -m unittest -v tests.test_pi_rpc_reusable tests.test_pi_session` and record expected failures.
- [x] Require exact response and settlement together; leave agent_end as a cycle boundary. Preserve stopReason through projection and reject terminal native failures. Fence events or failures whose ownership cannot be established after send.
- [x] Remove Prime's leading-settlement success assumption; allow a fresh agent_start to begin a continuation cycle. Keep tool ledger and application oracle checks.
- [x] Rerun targeted tests and directly affected Prime/transport tests.

## Task 2: Compact normalization

**Files:** `src/asterion/runtimes/pi_rpc.py`, `tests/test_pi_rpc_reusable.py`.

- [x] Replay valid, wrong-ID, wrong-command, mismatched-result and rejected compaction in both compact settings. Expect identical outcomes.
- [x] Validate wire command/result before replacing the response with canonical `{type, id, success}` for compact result validation; retain required failure metadata until validation.
- [x] Run `uv run python -m unittest -v tests.test_pi_rpc_reusable` and confirm all matrix cases pass.

## Task 3: Correct draft assumptions

**Files:** `docs/superpowers/specs/2026-09-19-asterion-prime-p1-verify-strategies-design.md`.

- [x] Replace disproven implicit-ack and no-second-execution claims with the proven queue-boundary finding.
- [x] Withdraw two-kernels/shared-session isolation, automatic fallback, rollback-on-close and arbitrary-process restoration claims. Describe actual child-session/transcript/authority/budget requirements as future design.
- [x] Record provider-free evidence only; live P1 verification remains unperformed.

## Execution evidence (2026-09-22)

- RED: `uv run python -m unittest -v tests.test_pi_rpc_reusable tests.test_pi_session` — 45 tests, 12 failures and 3 errors reproducing premature completion/implicit acknowledgment and compact inconsistency.
- RED: `uv run python -m unittest -v tests.test_asterion_prime_session` — leading settlement accepted and post-run continuation rejected (one failure, one error).
- RED: targeted unowned-event and direct-driver uncertainty tests also failed before their fencing changes.
- GREEN: `uv run --extra dci --extra prime python -m unittest -v tests.test_pi_rpc_reusable tests.test_pi_session tests.test_asterion_prime_session tests.test_dci_pi_rpc_recovery` — 87 passed.
- Compatibility: `uv run --extra dci --extra prime python -m unittest -v tests.test_asterion_dci_safe_recovery tests.test_asterion_dci_benchmark tests.test_dci_metrics tests.test_dci_reproduction tests.test_dci_benchmark_bamboogle_e2e tests.test_asterion_prime_backend tests.test_asterion_prime_p1_operator` — 155 passed.
- Focused `ruff check` and `git diff --check` passed. No model calls, schema changes, or new receipt fields. Existing real-Pi backend integration tests remain skipped and are not promoted to verified.
- DCI production code needed no edits. Its tests now model settlement plus exact-ID idle checks; explicit abort is an execution failure and cannot sign successful completion.
