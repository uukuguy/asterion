# Native P1 Task 5: native control and session-context attachment

## Scope

- Added the selected `asterion.prime-control@1.0.0` factory and packaged closed
  manifest under `asterion.control.providers.asterion_prime`.
- Added `AsterionPrimeControlPlaneClient`, which implements both the existing
  `ControlPlaneClient` and `SessionContextClient` shapes over one exact
  `PrimeAttachment`.
- Added focused control and clean attachment-reconstruction tests using the
  real `PrimeSessionBackend`, `FilePrimeSessionStore`, `FileCanonicalJournal`,
  `ControlHost`, `SessionContextManager`, and a fresh authority ledger.
- Registered the native control manifest as a wheel artifact. No shared
  protocol, backend, legacy Prime provider, or status/progress file changed.

## Contract implemented

- The factory validates the packaged manifest field-by-field against
  `CONTROL_COMMAND_TYPES`, `CONTROL_EVENT_TYPES`,
  `SESSION_CONTEXT_CAPABILITY`, and fixed identity/version/capability/
  compatibility/media-type constants before attaching.
- Construction is selected-only and requires the exact
  `prime.session-backend` host service, exact session/generation, selected
  application/version/runtime portfolio edge, private-root identity, authority
  identity/revision, and a live matching backend snapshot.
- Control commands, cursors, events, context commands, and context receipts are
  checked against the backend session generation and current authority
  revision. Returned events and receipts are reconstructed through the closed
  public validators and correlated with their request before return.
- Every host authority snapshot is mirrored to the same backend attachment.
  The backend records the mirror but does not debit usage; the host ledger
  remains the only context reservation/settlement owner.
- Client close is idempotent and only detaches its view. Backend, Pi, worker,
  witness, lease, and private store cleanup remain explicitly owner-controlled.
- All adapter/factory errors use one fixed public-safe message raised outside
  the internal exception handler, leaving both `__context__` and `__cause__`
  empty.

## RED / GREEN evidence

Initial RED:

```text
uv run python -m unittest -v \
  tests.test_asterion_prime_control tests.test_asterion_prime_recovery
FAILED: both modules raised ModuleNotFoundError because
asterion.control.providers.asterion_prime did not exist.
```

Initial GREEN after the narrow provider implementation was 10/10 focused
tests. The first recovery attempt exposed a missing test step: the rebuilt host
had not yet requested the provider suffix, so its journal cursor was 2 while
the backend cursor was 4. Adding the required `host2.pump()` replay step made
the full recovery test GREEN without changing production behavior.

Independent Astra review found one Important redaction defect. The added
regressions produced the following second RED:

```text
test_manifest_failure_is_redacted_and_does_not_attach:
  attachment generation was 1, expected 0
test_internal_errors_and_representations_are_redacted:
  public error.__context__ retained RuntimeError(SENTINEL...)
```

The fix validates the manifest before attaching and raises fixed public errors
after leaving the exception handler. Both regressions then passed, including
empty `__context__`/`__cause__` assertions.

## Recovery evidence

The recovery test performs one legal `session.create` before any prompt or
context effect, completes stage one, commits one real compact receipt, closes
host/client attachment one, reopens the same canonical journal, calls
`recover_control_host_state` with a pristine ledger from the same authority
envelope, attaches client two to the still-live backend, and constructs host
two. It verifies:

- journal position, authority revision/settled compact usage, event cursor,
  checkpoint, continuation, and kernel generation remain exact;
- attachment serial advances independently of the unchanged kernel generation;
- host two replays only the backend event suffix after the journal cursor;
- continuation resume changes neither prompt nor compact call counts;
- stage two increments only the prompt count, leaving compact at exactly one;
- both hosts detach without backend cleanup; and
- explicit backend-owner cleanup closes Pi and worker exactly once.

The `session.describe` adapter test preserves Task 4 semantics: before an
authenticated compact count exists it returns the definitive rejected receipt
`context-count-unavailable`, never zero or a stale estimate.

## Verification

Provider-free commands run during implementation:

```text
uv run python -m unittest -v tests.test_asterion_prime_control \
  tests.test_asterion_prime_recovery tests.test_control_provider \
  tests.test_control_recovery
PASS: 43 tests (Gate G4)

uv run python -m unittest -q tests.test_prime_control_factory \
  tests.test_prime_control_client tests.test_prime_session_context_parity \
  tests.test_prime_diagnostic_session_recovery_adapter \
  tests.test_prime_diagnostic_session_recovery_completion \
  tests.test_prime_diagnostic_session_recovery_receipt
PASS: 78 tests (legacy Prime provider/context/recovery regression)

uv run ruff check <Task 5 provider and test files>
PASS
uv run ruff format --check <Task 5 provider and test files>
PASS
uv run pyright <Task 5 provider and test files>
PASS: 0 errors, 0 warnings
git diff --check
PASS

uv build --wheel
PASS: dist/asterion-0.1.0-py3-none-any.whl
unzip -l ... | rg asterion/control/providers/asterion_prime
PASS: client.py, factory.py, and resources/control-plane.json are present
```

The independent review reported no Critical findings. Its one Important
redaction finding was reproduced and fixed before the final gates; the focused
follow-up review is recorded in the task handoff.

## Unfinished boundary

This task verifies native Prime control/context attachment and clean
in-operator `ControlHost` reconstruction while the same backend, Pi lifecycle,
and worker remain live. It does not claim backend/Pi/worker/operator-process
crash resurrection, native P1 application publication, restricted P1 worker or
oracle delivery, installed native P1 acceptance, a live provider call, full
repository `make check`, promotion, or any P2-P7 capability.
