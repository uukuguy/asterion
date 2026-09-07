# P7a Task 6 report

Status: DONE

Implemented the autonomous Prime solving gateway and bounded DeepSeek adapter from baseline `64f4048ed7bda215dcec5726431ebce851191253`.

## Contract

- One Prime prompt, at most 128 total model callbacks (normal plus summary), and at most 128 persistent IPython callbacks.
- Prime model context window 131,072; compaction enabled with reserve 8,192, recent 32,768, and agent-callable compaction disabled.
- IPython is sequential. A solve stops only when the operator tool result carries private `details.broker_terminal == "LEVEL_SOLVED"`; assistant prose and ordinary output cannot latch success.
- Private protocol `asterion.prime-p7-solving-gateway/v1`, 16,777,216-byte frames, exact identity, contiguous sequences, correlated callbacks, one prompt, cancellation, close, and empty Node/provider-child environments.
- DeepSeek normal callbacks expose only IPython with `tool_choice: "auto"`; summary callbacks expose no tools. Calls are serialized through one provider child, use temperature 0, no retry, and 4,096 output tokens per callback.
- Cumulative limits: 128 callbacks, 2,000,000 input tokens, 200,000 output tokens, 5,000,000 cost microunits, and 3,600 seconds. Canonical callback bodies are capped at 8,388,608 bytes before fork.
- `finalize()` seals actual accumulated usage only while idle, supports a zero-call idle seal, and rejects reuse.

## TDD evidence

The four aggregate tests were added first. Initial Node failures were `ERR_MODULE_NOT_FOUND` for both solving modules; initial Python failures were `ModuleNotFoundError`/`ImportError` for the new gateway and provider. After implementation all four scenarios pass.

## Verification

- `npm --prefix packages/typescript/prime-gateway test -- test/p7-solving-session.test.mjs test/p7-solving-bridge.test.mjs` — 2 passed.
- `uv run python -m unittest -v tests.test_prime_p7_solving_gateway tests.test_prime_p7_solving_sdk_provider` — 2 passed.
- `uv run ruff check` on the four Python task paths — passed.
- `uv run python -m compileall -q` on the four Python task paths — passed.
- `uv run pyright` on both Python production modules — 0 errors, 0 warnings.
- TypeScript build is part of the focused Node command and passed.

The Python 3.14 test run emits the interpreter's existing multithreaded-`fork()` deprecation warning. The provider immediately enters a bounded child path, closes unrelated descriptors, clears the environment, and reaps on cancellation; no test or typecheck failure remains.

## Compaction transition hardening

The provider now records each summary request's exact serialized transcript span and semantic role. `accept_compaction()` derives one exact prefix replacement, records the accepted before/after transition, and the next normal callback must equal the canonical summary wrapper plus the untouched suffix. A retained-suffix mutation is covered by the existing compaction aggregate test and fails before a provider child starts.

Focused verification after this fix: Node 2/2, Python 2/2, production Ruff passed, and production Pyright reported 0 errors and 0 warnings.

## Astra production compaction completion wiring

Baseline for this handoff: `3d1819b8ad83a31c940138c92d8290c6091eb04d`.

RED: `uv run python -m unittest -v tests.test_prime_p7_solving_gateway` failed in `gateway.prompt()` with `PrimeP7SolvingGatewayError` after a fake bridge emitted a `compaction.accepted` frame. That proved the production gateway receive loop did not admit compaction completion events.

Implemented the smallest private event path:

- TypeScript session captures `agent.state.messages` at `compaction_start`, records each summary callback's exact SDK summary span, then captures the compacted `agent.state.messages` at successful `compaction_end`.
- TypeScript bridge emits a private `compaction.accepted` event with `replaced_messages`, `replacement_messages`, and `summary_spans` on the existing identity-bound framed protocol.
- Python gateway consumes `compaction.accepted` while waiting for command results and calls the bound provider's `accept_compaction()`.
- Python provider now validates the complete after-history and cross-checks `summary_spans` against pending summary requests before allowing the next normal callback.
- The compaction aggregate test now accepts compaction through `PrimeP7SolvingGateway` framed transport instead of directly hand-calling the provider.

Focused verification after this wiring:

- `npm --prefix packages/typescript/prime-gateway test -- test/p7-solving-session.test.mjs test/p7-solving-bridge.test.mjs` — 3 passed.
- `uv run python -m unittest -v tests.test_prime_p7_solving_gateway tests.test_prime_p7_solving_sdk_provider` — 2 passed.
- `uv run ruff check src/asterion/applications/prime_agent/operator/p7_solving_gateway.py src/asterion/applications/prime_agent/operator/p7_solving_sdk_provider.py tests/test_prime_p7_solving_gateway.py tests/test_prime_p7_solving_sdk_provider.py` — passed.
- `uv run pyright src/asterion/applications/prime_agent/operator/p7_solving_gateway.py src/asterion/applications/prime_agent/operator/p7_solving_sdk_provider.py` — 0 errors, 0 warnings.
