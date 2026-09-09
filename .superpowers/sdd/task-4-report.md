# Task 4 report: Asterion-prime session and AgentRuntime

## Scope delivered

- Added the source-independent `AsterionPrimeSession` over the injected common
  `PiRpcSession`, exact `prime.ipython` binding, and its already-open pinned
  single-run lease. Host/operator integration retains ownership of resolution
  and preflight; the session does not discover paths, read provider settings,
  compose, authorize, retry, or persist.
- Enforced the fixed P7 slice limits: 128 model callbacks, 500 tool callbacks,
  and a 3,600,000 ms deadline. A session accepts one active request, consumes
  its lease once, and rejects reused run IDs.
- Added immutable, redacted `PrimeToolCall` / `PrimeToolResult` values and a
  deterministic ledger that accepts each call/result ID once and refuses a
  successful seal for unmatched or uncertain effects.
- Added the exact `asterion.prime` runtime manifest with sorted capabilities
  `prime.arc-agi-3-solving` and `prime.tool.ipython`.
- Normalized only closed Pi native event shapes into contiguous
  `asterion.agent-runtime/v1` events. Model prose, provider payloads, IPython
  arguments/results, stderr, extension paths, and launch values are not placed
  in public events or errors. Terminal completion/cancellation contains only
  status; transport failures use one fixed public-safe code/message.
- The session owns lease closure after completion, failure, cancellation,
  protocol rejection, explicit close, and unstarted-object finalization.

## Clarified constructor seam

The task owner confirmed during implementation that construction receives all
three of the following values: an injected common `PiRpcSession`, an exact
`PiExtensionBinding`, and the already-open `PiExtensionLease`. Construction
fails closed unless the binding is exactly `prime.ipython`, its capability is
exactly `prime.tool.ipython`, the lease belongs to that binding, and the
transport command, environment, inherited descriptors, and deadline reflect
the lease launch material exactly. The session does not call `preflight()`.

## Files

- `src/asterion/agents/prime/__init__.py`
- `src/asterion/agents/prime/session.py`
- `src/asterion/agents/prime/tools.py`
- `src/asterion/runtimes/asterion_prime.py`
- `src/asterion/runtimes/pi_extensions.py` (approved lease identity expansion)
- `tests/test_asterion_prime_session.py`
- `tests/test_asterion_prime_runtime.py`
- `tests/test_pi_runtime_extensions.py` (focused identity regression)
- `.superpowers/sdd/task-4-report.md` (this required report)

## TDD evidence

Initial missing-product RED:

```text
uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_asterion_prime_session tests.test_asterion_prime_runtime

ERROR: ModuleNotFoundError: No module named 'asterion.agents.prime.session'
ERROR: ModuleNotFoundError: No module named 'asterion.runtimes.asterion_prime'
Ran 2 tests; FAILED (errors=2), exit 1.
```

Initial focused GREEN:

```text
uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_asterion_prime_session tests.test_asterion_prime_runtime
Ran 16 tests in 0.071s; OK.
```

Self-review RED/GREEN:

- An unstarted abandoned session test first failed with
  `TypeError: cannot create weak reference to 'AsterionPrimeSession' object`;
  the weakref finalizer implementation then passed.
- Malicious tool mappings initially raised raw `RuntimeError` values containing
  `PRIVATE-MAPPING-*`, and an explicitly closed session could still invoke its
  transport. After normalization and the closed-lease admission check, both
  focused tests passed with no retained exception context.

Independent-review RED/GREEN:

- The extra-environment regression initially accepted
  `PRIVATE_PROVIDER_SECRET`; the lookalike-session regression initially allowed
  an arbitrary callable object to expose the `asterion.prime` identity. Both
  failed as expected before their fixes.
- Construction now requires exact transport/lease environment equality, and
  the runtime adapter requires an exact validated `AsterionPrimeSession`.
  Focused rerun: 2 tests, OK.
- The review's type-narrowing finding was fixed; scoped pyright reports
  `0 errors, 0 warnings, 0 informations`.

Final protocol and detachment GREEN:

```text
uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_asterion_prime_session tests.test_asterion_prime_runtime \
  tests.test_runtime_protocol tests.test_asterion_prime_architecture
Ran 30 tests in 0.067s; OK.
```

Final static verification:

```text
uv run ruff check <six owned implementation/test files>
All checks passed!

uv run python -m py_compile <six owned implementation/test files>
exit 0

uv run pyright <Task 4 source/test files>
0 errors, 0 warnings, 0 informations

git diff --check -- <Task 4 owned files and report>
exit 0
```

## Self-review

- Confirmed one contiguous stream and one terminal for every returned stream;
  malformed native events raise a generic `ProtocolError` before buffered
  public events are yielded.
- Confirmed tool code/results and model deltas are validated/accounted for but
  not projected onto the public stream; only call identity/name, error status,
  and numeric usage cross the adapter boundary.
- Confirmed duplicate/unmatched results, duplicate terminals, unknown native
  event types, callback overflow, request deadline overrides, active overlap,
  reused IDs, closed leases, and launch-material mismatches fail closed.
- Confirmed no Prime Agent source, SDK, loader, launcher, or source lock is
  referenced; the Task 1 static detachment gate passes.
- Independent review found no remaining critical/high issue after its three
  findings were resolved.

## Concerns and boundary

- This is only the framework/session protocol slice. It does not register a
  provider, assembly, application, P7 extension, or live-solving route.
- Exact child environment equality intentionally prevents provider credentials
  or arbitrary `.env` values from being smuggled into this runtime slice.
  Subsequent application integration must use the approved host-injection
  boundary; widening child environment inheritance requires an explicit
  contract change and privacy review.
- A protocol-invalid Pi callback raises `ProtocolError` rather than returning a
  partial failure stream. This preserves the brief's explicit fail-closed
  unmatched-result behavior and ensures no partially translated private event
  is observable.

## Reviewer follow-up: exact lease, command, and terminal boundaries

The post-commit reviewer identified five additional boundary gaps. The focused
fix retains the original Task 4 architecture while tightening admission and
publication:

- Native tool starts remain private until a certain matching result arrives;
  the session then publishes the `tool.call` and `tool.result` together.
  Failure or cancellation discards an unmatched staged call, so every returned
  stream remains valid.
- A transport-originated `ProtocolError` is normalized to the one fixed
  `Asterion-prime transport protocol failed` error with no retained exception
  context. Callback-local validation uses an explicit internal rejection path
  and exposes only static public-safe messages; ledger unit errors retain their
  specific contract diagnostics.
- `PiExtensionBinding` now derives an opaque domain-separated canonical SHA-256
  fingerprint over its immutable binding fields. Preflight copies it into an
  immutable `PiExtensionLease`; session admission compares the two directly.
  Matching basenames/environments cannot substitute a lease from another
  absolute binding path.
- The host injects an immutable `approved_command`; session construction
  requires full tuple equality with `PiRpcConfig.command`, in addition to the
  pinned loader suffix checks. Extra executable or flag prefixes fail closed.
- External `close()` refuses an active request without closing or detaching its
  lease. The run's `finally` path remains the sole active-run cleanup owner.

Follow-up RED evidence:

```text
Lease identity / approved command:
- AttributeError: PiExtensionBinding had no binding_fingerprint.
- TypeError: AsterionPrimeSession rejected the new approved_command keyword.

Publication / transport / close:
- failure after tool_execution_start produced a protocol-invalid unmatched call.
- transport ProtocolError exposed PRIVATE-TRANSPORT-PAYLOAD.
- close() during a gated active run did not raise.

Independent re-review:
- direct assignment to lease._binding_fingerprint succeeded, allowing identity
  mutation; the new regression failed because AttributeError was not raised.
- Follow-up review found that deleting `_initialized` reopened normal slot
  assignment; its regression likewise failed before deletion was guarded.
```

Each RED was observed before its corresponding implementation. The immutable
lease fix guards both assignment and deletion after construction while
`close()` changes only `_closed` through the class-owned internal path.

Follow-up GREEN evidence:

```text
uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_asterion_prime_session tests.test_asterion_prime_runtime \
  tests.test_runtime_protocol tests.test_asterion_prime_architecture \
  tests.test_pi_runtime_extensions
Ran 61 tests in 0.316s; OK.
```

Independent re-review found no critical/high issue; its sole medium immutable
backing-slot finding was covered by a failing regression and then fixed.
The final follow-up re-review returned CLEAN after both normal assignment and
sentinel-deletion bypasses were closed.

Follow-up static verification:

```text
uv run ruff check <expanded Task 3/4 scoped files>
All checks passed!

uv run python -m py_compile <expanded Task 3/4 scoped files>
exit 0

uv run pyright <Task 4 files plus pi_extensions.py>
0 errors, 0 warnings, 0 informations

git diff --check -- <expanded Task 3/4 scoped files and report>
exit 0
```

## Reviewer follow-up: hostile callback exception redaction

One remaining review found that a hostile native `Mapping.get()` implementation
could raise a secret-bearing `ProtocolError`. The callback wrapper previously
copied `str(error)`, incorrectly treating exception type as proof that its
message was code-owned.

RED evidence:

```text
uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_asterion_prime_session.TestAsterionPrimeSession.\
test_hostile_callback_protocol_errors_are_fixed_and_context_free

Both `outer` and `nested` subtests failed because the observed message was
`PRIVATE-MAPPING-PROTOCOL-ERROR` instead of the fixed native-event error.
```

The fix gives static local callback diagnostics a private
`_NativeEventRejected` channel. Every other exception crossing an untrusted
native mapping operation, including `ProtocolError`, becomes the fixed
`Asterion-prime native event is invalid` error. The public exception retains
neither the hostile message nor an exception context or cause.

Focused GREEN evidence:

```text
uv run python -W error::ResourceWarning -m unittest -v \
  <hostile outer/nested regression> <unmatched-result regression> \
  <model-cap regression> <tool-cap regression>
Ran 4 tests in 0.013s; OK.

uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_asterion_prime_session
Ran 22 tests in 0.098s; OK.

uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_asterion_prime_session tests.test_asterion_prime_runtime \
  tests.test_runtime_protocol tests.test_asterion_prime_architecture \
  tests.test_pi_runtime_extensions
Ran 62 tests in 0.360s; OK.

uv run ruff check <expanded Task 3/4 scoped files>
All checks passed!

uv run python -m py_compile <expanded Task 3/4 scoped files>
exit 0

uv run pyright <Task 4 files plus pi_extensions.py>
0 errors, 0 warnings, 0 informations

git diff --check -- <hostile-callback scoped files and report>
exit 0
```

Independent focused re-review returned CLEAN/APPROVE after direct outer and
nested hostile callback probes and found no attacker-controlled
`ProtocolError(str(...))` path in the scoped files.
