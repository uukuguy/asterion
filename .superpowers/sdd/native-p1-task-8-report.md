# Native P1 Task 8 — operator coordination and installed fixed preset

## Delivered boundary

Implemented the application-owned `P1OperatorResources`, private
`P1Coordination` gates, installed module launcher, and
`make asterion-prime-p1-run`. No generic framework module reads `.env`, owns an
operator credential, or imports the legacy Prime application implementation.
The launcher accepts no provider/model/cost/deadline arguments; the runner input
is exactly `fixed-small-verification`.

The provider-free closed loop uses real composition, native runtime and
capability implementation, `PrimeSessionBackend`, persistent IPython worker,
backend store, canonical file journal, authority ledger, `ControlHost`, recovery
constructor, context manager, runner, oracle, and cleanup/receipt seal. Only the
model/Pi adapter supplies scripted fixture cells and authenticated witness
frames. Fixture code is in tests, never production prompts or seeded globals.

The success test asserts this exact trace:

```text
backend.open → host1.open → runner.start → stage1.complete
→ compact.admit → compact.provider-call → compact.persist → host1.close
→ journal.reopen → host2.recover → authority.sync → resume.admit
→ resume.persist → stage2.release → stage2.complete → oracle.pass
→ host2.close → worker.close → pi.close → backend.close → runner.terminal
```

It additionally asserts three independent prompt turns, exactly one compact,
one Pi close and worker reap, the same worker/checkpoint identity across actual
host reconstruction, and reconstructed authority usage of 16,015 tokens
(16,000 conservative compact debit plus 15 normalized prompt tokens).
All five runtime events—including the artifact and terminal—are observed only
after the exact complete owner-cleanup receipt exists. The coordinator does
not consume, manufacture, or replay runtime events.

## Failure and owner-lifetime evidence

- Cancellation is exercised at thirteen coordination barriers. Pre-dispatch
  compact rejection and an authenticated, typed no-mutation rejection retain
  the prior checkpoint without an outstanding effect; neither releases stage
  two. Malformed/post-mutation witness uncertainty fences the backend, and
  reconstruction, stage-two, deadline and budget failures cannot fabricate a
  completed receipt.
- The controller approved the minimal backend addition
  `PrimeBackendBudgetError(PrimeBackendError)`. It carries a fixed public-safe
  message and is raised only before `effect-started` for demonstrable
  application/aggregate/cost/deadline or fixed-cap exhaustion. Missing budget
  configuration and post-dispatch uncertainty remain ordinary failures. The
  backend dimension matrix verifies zero provider dispatch and no store
  mutation. The operator test constructs a real backend with aggregate cap
  five: the first prompt uses five tokens, the second dispatches zero times,
  and the real runtime emits `p1_budget_limited`.
- Effects, milestones, opening/reconstruction/verification awaits, cleanup and
  runner settlement are bounded. Teardown shares an absolute deadline, with
  time reserved for later resource owners instead of allowing a stuck host to
  consume the whole cleanup window. There is no cancel-then-unbounded-gather
  path in the new coordinator or launcher.
- Isolated subprocess regressions retain cancellation-resistant owners without
  a test-provided release: host1 reconstruction close, host2 final close,
  backend close and an active model effect. Each returns protocol failure
  within the fixed bound, with the real worker PID dead, Pi closed once,
  extension lease closed and private store root absent. No completed/artifact
  projection or `runner.terminal` is permitted. The reconstruction case also
  asserts that neither host2 nor stage2 was created/released.
- Forced Pi cleanup retains the real process owner independently of the
  command lock, kills its process group, and runs `rpc.stop()` in a daemon
  cleanup thread. It verifies the process is reaped and no RPC process remains.
  A real `PiRpcSession` running a local provider-free Python child is tested
  with its command lock held; the child is dead before any test cleanup runs.
  An explicit incomplete backend cleanup with `pi_closed=False` also enters
  this independent path; its narrow regression failed with zero Pi closes
  before the fix and passed afterwards, without promoting cleanup to complete.
- Root deletion is reported only after successful removal and enclosing-root
  cleanup. Injected root cleanup failure yields incomplete cleanup and protocol
  failure, not a terminal/artifact. Worker-close failure still reaches Pi and
  does not receive a successful seal.
- The Python 3.10-compatible controlled event-loop entry has bounded task and
  async-generator shutdown. The module entry flushes public failure and exits
  without Python's unbounded executor-thread join on failure. Separate child
  process regressions cover a stubborn coroutine and a permanent default
  executor thread, with fixed public-safe stdout and empty stderr. Residual
  owners are never described as clean merely because the launcher can exit.

## Installed operator and preflight

The Make preset builds one temporary wheel beneath the shared repository
mount, traps cleanup, reuses the configured Orb machine, removes `PYTHONPATH`,
and invokes installed Python with `--isolated` and `-I` from `/tmp`. It injects
only the fixed operator root and worker interpreter. No browser is started.
The worker path is lexically normalized so the preset's `../external-prime`
spelling agrees with the exact expected path, while worker executable and
entrypoint fingerprint checks remain in force.

Only the operator resolves `.env`. Preflight rejects source-checkout imports,
checks pinned worker IPython, verifies the exact external compaction closure,
loads fixed DeepSeek model price metadata, and quotes the fixed compaction
reservation. A provider-free probe verifies nonempty compaction preparation
with automatic compaction disabled. Worker and Pi start only after the static
operator checks; dependency/extension preflight precedes worker launch.

The installed-route test builds a fresh shared-mount wheel, runs outside the
checkout with `PYTHONPATH` unset and `python -I`, checks package/resources and
entrypoint distribution ownership, constructs the actual operator worker,
lease, bridge and unopened Pi backend without a provider, closes those owners,
then runs the same fake-model real-resource closed loop from the installed
package. It asserts no legacy `asterion.applications.prime_agent` import.

Two existing P7 launcher assumptions could not be reused literally:

- Its `dist/rpc-entry.js` is absent from the locked checkout. Native P1 uses
  a fixed inline Node import of the verified `dist/main.js` exported `main`,
  retaining one Pi adapter and the same locked closure.
- The verifier module dispatches its CLI when argv[1] equals its own path;
  the price probe now supplies a separate fixed argv[1] and parses following
  positional inputs. A real source-lock/price/preparation probe covers this.

Installed construction also exposed an invalid 600-second witness timeout;
the witness's closed contract permits at most 60 seconds. The operator now
uses fixed 60 seconds within the enclosing 600-second run limit.

## RED / GREEN and verification

Initial choreography and Make tests were run RED for the absent operator and
preset. Focused tests then passed against the implementation. Review regressions
were also observed RED before fixes: lexical worker path, premature root
cleanup success, unbounded cancellation settlement, typed backend budget
classification, reconstruction/final-host hangs, launcher executor shutdown,
missing locked Pi entry, probe argv dispatch, and actual installed construction.
The real command-lock forced-Pi regression failed for the absent independent
close path, then passed with the process-owner implementation.

Fresh combined gate:

```bash
uv run --extra prime python -W error::ResourceWarning -m unittest -v \
  tests.test_asterion_prime_p1_operator tests.test_prime_make_presets \
  tests.test_asterion_prime_p1_installed tests.test_asterion_prime_p1_runtime \
  tests.test_asterion_prime_p1_provider tests.test_asterion_prime_runtime \
  tests.test_asterion_prime_control tests.test_asterion_prime_recovery \
  tests.test_asterion_prime_p1_worker tests.test_asterion_prime_p1_oracle \
  tests.test_asterion_prime_backend
```

**PASS: 137 tests, 28.218 seconds**, no skips. Subsequent strengthened five-token
budget and explicit forced-Pi reaping assertions also passed. Final named G6
was rerun after those assertions:

```bash
uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_asterion_prime_p1_operator tests.test_prime_make_presets \
  tests.test_asterion_prime_p1_installed
```

**PASS: 31 tests, 18.396 seconds**, no skips, including the final incomplete-Pi
cleanup regression.

Scoped Ruff checks pass for the three changed production files and three
changed test files. Ruff formatting passes for the two new production modules
and new operator test. Scoped Pyright passes for operator, coordination,
backend and the new operator test: zero errors and warnings. Existing backend
test-file Pyright debt is not claimed as passing. `uv lock --check`,
`git diff --check`, and `make -n asterion-prime-p1-run` pass.

```text
uv build --wheel --out-dir /tmp/asterion-native-p1-task8-wheel.vEf6Tz
PASS: asterion-0.1.0-py3-none-any.whl
SHA-256: 461340a4b40800c97f7abd646aa805427e7cf9a2f373bf7053d89b62d46b9713
```

Wheel inspection confirms operator, coordination, the packaged extension, and
entrypoint metadata. Process inspection after completed suites found no live
P1 worker or native Pi launcher child.

## Explicit remaining boundary

`make promotion-check` was rerun and remains **External-limited** at the existing
`external Prime source binding could not be created` boundary. It is not PASS.
Full `make check`, the live Orb preset, paid provider calls, real model-generated
P1 solution/compaction, and live acceptance are **Not rerun** in Task 8.
Installed provider-free success is not evidence of live model capability.
No full benchmark, pricing/network model request, browser action, or live
provider execution was performed.

Only Task 8 files, this report and the explicitly approved minimal backend
exception/test change belong to this task's commit. Other worktree changes,
historical documents, temporary directories and status/JOURNAL edits are
preserved and excluded.

Controller critical review: **Approved, zero remaining findings** after the
bounded-owner, process-lock, installed-construction and typed-budget repairs.
