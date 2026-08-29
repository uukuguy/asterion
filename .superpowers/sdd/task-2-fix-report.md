# H-035 Task 2 Fix Report — Host Client Recovery

## Scope

Closed every Task 2 independent-review finding in the host-owned client
endpoint, canonical journal, and `ControlHost` boundary. The implementation
does not add provider, retry, discovery, authorization, model, or upload
authority. Existing uncommitted state files under `docs/status/` are excluded
from this fix.

## Root cause and changes

1. **Crash-prefix intent recovery:** `client.intent.accepted` was treated as
   if it implied provider delivery. Recovery now classifies it as a pending
   dispatch until the immediately following, exact `command.accepted` record
   for `client:<intent_id>` is present. An accepted-only prefix retries once;
   a persisted control command is not redelivered; a divergent retry fails
   closed. Interleaving or a command with different identity/payload rejects
   endpoint recovery rather than being silently skipped.

2. **Verified ControlHost handoff:** `ControlHost.dispatch()` again requires
   its journal cursor to equal the current tail. The endpoint passes each
   freshly accepted client record through `advance_client_record()`, which
   verifies a one-record, session-bound suffix before advancing the host
   cursor. Arbitrary newer tails and unrelated interleaving therefore remain
   rejected.

3. **Observation cursor and event prefix:** The observation source cursor now
   uses the final accepted `source_sequence`, not event count. Source sequences
   are strictly monotonic; projected public event sequences remain contiguous.
   Incremental checks reject duplicate event IDs, post-terminal events,
   repeated tool call IDs, completions without starts, and terminals with
   active calls. At a terminal, the complete endpoint event list is validated
   with `validate_client_event_stream`.

4. **Live private authority:** `ClientPrivateValueService` now requires an
   authoritative revision callback. It checks that live revision before the
   descriptor/read and again afterwards, so caller-provided revision claims
   cannot preserve access after host authority changes. Existing cancellation,
   deadline, expiry, descriptor, size, and digest checks remain in place.

5. **Canonical observation records:** Journal admission validates and stores
   the same canonical observation values. The former `str(...)` coercions are
   removed, so malformed non-string identities and fields cannot validate then
   be retained in noncanonical form.

## Test-first evidence

### RED

New focused tests were added before implementation. The first focused run was
red as expected:

```text
uv run python -m unittest -v tests.test_client_session tests.test_control_journal tests.test_control_host
```

It failed because `ClientPrivateValueService` had no live-authority source,
accepted-only recovery returned without dispatch, noncanonical observations
were accepted, and the new observation/event-prefix tests could not construct
the required service. These failures isolated the reviewed boundaries rather
than exposing private values.

### GREEN / verification

```text
uv run python -m unittest -v tests.test_client_session tests.test_control_journal tests.test_control_host
# Ran 32 tests — OK (run twice)

uv run python -m unittest -v tests.test_agent_client_protocol
# Ran 8 tests — OK

uv run pyright src/asterion/client/private.py src/asterion/client/session.py src/asterion/control/journal.py src/asterion/control/manager.py
# 0 errors, 0 warnings, 0 informations

make lint
# compileall and ruff check passed

git diff --check
# exit 0
```

## Self-review

- The shortest recoverable intent prefix (`client.intent.accepted` only)
  dispatches exactly once on identical retry. The next durable prefix
  (`command.accepted`) is deliberately not redelivered because transport state
  is uncertain.
- Client record recovery only permits the exact intent-to-command and
  observation-to-event ordering produced by the endpoint. Control recovery may
  still ignore client records for state reduction, but the endpoint validates
  their ordering and identity before exposing a recovered client session.
- Journal records remain body-free and immutable; errors stay fixed/redacted.
- `advance_client_record()` is a narrow cursor handoff only. It neither
  authorizes commands nor retries effects, and `dispatch()` retains its
  fail-closed position check.
