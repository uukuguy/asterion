# Task 9 report: execute admitted control actions once

## Result

Implemented the provider-free action execution and settlement lifecycle behind
the host-owned admission boundary. `ActionExecutionReceipt` is a frozen,
closed, canonical and body-safe result carrying only action/receipt identity,
five validated usage counters, sorted unique artifact IDs and sorted unique
media types. `ActionExecutionFailure` is the controlled exception protocol for
proved `failed`, `cancelled` and `uncertain` outcomes; returning it as a value,
returning another object, raising an unknown exception, or returning an invalid
receipt fails closed as `uncertain`.

The host now persists and successfully sends admission before execution. It
then appends `action.running` as the durable executor-contact fence, calls the
executor once with the read-only cancellation signal, previews exact authority
settlement before journaling a receipt, appends `action.receipted`, settles the
reservation once, transitions canonical state, projects only safe Pathlight
digests/counts/usage, persists one stable terminal command and finally sends
it. Rejection and pre-start cancellation never contact the executor. Unknown
progress preserves the reservation and never writes an invalid receipt.

Recovery exposes only proposals, admission commands, terminal commands and
running fences reconstructed from the fully validated journal. A persisted
admission without a running fence is resent and can execute once. A running
fence without a receipt is never re-executed and becomes stable `uncertain`.
A durable receipt is settled exactly once and completes with the same receipt
reference. A persisted terminal command is resent idempotently; terminal
transport failure does not roll back usage, receipt or state. Different
terminal command identities/semantics fail closed. Both a failed admission send
and a failed terminal send can be retried on the same live host with the exact
persisted command; the executor is contacted only after successful admission
delivery and is never contacted again for terminal retry. Commands enter the
admission retry set only after successful journal persistence. Constructed
terminal commands are retained across persistence failure, but a separate
durability marker prevents delivery until journal persistence succeeds;
recovered terminal commands initialize with that marker.

Recovery now accepts only exact `admission:{action_id}` and
`terminal:{action_id}` command identities. A terminal requires the durable
admission and running fences, except for the exact admitted
`cancelled-before-start` transition. Success requires the exact durable
receipt; terminal commands cannot synthesize running state. Task 8 journals
whose durable receipt predates the explicit running record remain recoverable.

No TypeScript or Rust execution implementation changed. No provider, model,
Agent, Judge or network operation was run.

## TDD evidence

The required command was first run before production implementation:

```text
uv run python -m unittest -v \
  tests.test_control_execution tests.test_control_host tests.test_control_pathlight

RED: exit 1
- tests.test_control_execution could not import asterion.control.execution.
- tests.test_control_pathlight failed for the same missing contract.
- the updated host success lifecycle test failed for the same missing feature.
```

After implementation and crash/recovery refinement:

```text
uv run python -m unittest -v \
  tests.test_control_execution tests.test_control_host tests.test_control_pathlight
GREEN: 23 tests, PASS
```

Independent review identified two gaps and drove a second RED/GREEN cycle:

```text
uv run python -m unittest -v \
  tests.test_control_execution tests.test_control_host \
  tests.test_control_pathlight tests.test_control_recovery \
  tests.test_control_file_journal
RED: exit 1
- same-host admission and terminal transport retries were lost
- malformed terminal prefixes could synthesize running/terminal state

GREEN: 54 tests, PASS
```

A second review found that terminal persistence failure occurred after state
transition but before the command entered the pending map. The same host then
discarded the terminal on its next pump. A focused RED test reproduced this
loss, including two consecutive persistence failures:

```text
uv run python -m unittest -v \
  tests.test_control_execution.TestControlExecution.test_same_host_persists_terminal_before_sending_after_failures
RED: exit 1; the second pump did not retry terminal persistence
GREEN: 1 test, PASS
```

The terminal is now retained when constructed while durable send authority is
tracked separately. Each failed persistence attempt sends nothing; a later
pump persists and sends the same terminal once without executor re-entry.

The Task 9 matrix covers strict receipt/failure construction and redaction,
unauthorized no-contact, admission-before-executor ordering, cancellation
before and during execution, controlled failure, unknown exception, malformed
returned failure, wrong-action and over-budget receipts, persisted admission
recovery, durable running recovery, durable receipt recovery with a real
`FileCanonicalJournal` reopen, terminal-send failure/restart, equal terminal
replay, divergent terminal rejection, same-host admission/terminal retry,
repeated terminal-persistence failure with zero undurable sends,
never-send-before-persistence, canonical recovery prefixes, and Pathlight
safety/failure isolation.

## Verification

```text
uv run python -m unittest -v \
  tests.test_control_execution tests.test_control_host \
  tests.test_control_pathlight tests.test_control_recovery \
  tests.test_control_file_journal
PASS: 55 tests

uv run python -m unittest discover -v -s tests -p 'test_control*.py'
PASS: 103 tests

uv run pyright [Task 9 control source and test files]
PASS: 0 errors, 0 warnings

make lint
PASS

make check
PASS: 1549 Python tests, lint, 85 Markdown files/54 links,
      21 TypeScript runtime tests, 32 context-extension tests,
      Rust tests/fmt/clippy, and wheel/sdist build

git diff --check
PASS
```

## Self-review and remaining risks

- Python remains the sole orchestration/runner owner; manifests gained no
  authority, command, provider configuration, executable path or mutable state.
- `action.running` is accepted only after the exact persisted admitted command
  and before a receipt. Invalid receipts are preview-rejected before the
  canonical prefix, leaving the reservation available for conservative
  uncertain recovery.
- Public errors, reprs, journal records and Pathlight projections do not retain
  prompt, answer, provider body, private path or raw artifact identity.
- Execution is deliberately sequential. The only cancellation channel is the
  injected read-only signal; unknown task/process interruption after the
  running fence relies on restart to project `uncertain`.
- Proven failed/cancelled actions conservatively retain their unused budget
  reservation because the authority contract has no separately durable
  release receipt. This avoids fabricating usage or release authority.
- Task 8's historical receipt-before-running prefix still establishes running
  state through its durable `action.receipted` record. A terminal can no longer
  create that fence or claim success without the exact receipt.

## Files

- `src/asterion/control/execution.py`
- `src/asterion/control/manager.py`
- `src/asterion/control/state.py`
- `src/asterion/control/journal.py`
- `src/asterion/control/evidence.py`
- `src/asterion/control/recovery.py`
- `src/asterion/control/authority.py`
- `src/asterion/control/__init__.py`
- `tests/test_control_execution.py`
- `tests/test_control_host.py`
- `tests/test_control_pathlight.py`
- `tests/test_control_recovery.py`
- `.superpowers/sdd/task-9-report.md` (ignored evidence only; not staged)

The pre-existing dirty `.superpowers/sdd/task-8-report.md`,
`docs/status/JOURNAL.md` and `docs/status/RESUME-NEXT-SESSION.md` were neither
edited nor staged by Task 9.
