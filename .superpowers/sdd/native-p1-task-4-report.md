# Native P1 Task 4: shared backend and durable store

Initial implementation commit: `de261473` (`feat: add shared prime session backend`).
Review repair commit: the commit containing the repair section below, subject
`fix: enforce prime live recovery and compact terminals`.

## Scope and implemented interfaces

- Added immutable `PrimeBackendIdentity`, `PrimeBackendSnapshot`, and
  `PrimeCheckpoint`; exact identity covers the Pi command, extension, worker,
  continuation, private root, application/version/runtime, and finite ceilings.
- Added `FilePrimeSessionStore`: one lifetime writer lock, canonical JSONL,
  owned private root/files, symlink/hardlink/replacement rejection, exact append
  positions, fsync before memory advancement, immutable records, per-record and
  aggregate caps, content-addressed transcript/summary/usage blobs, and validated
  checkpoint chain/cursor/digests. `private_root_identity` (also exported as
  `prime_private_root_identity`) hashes canonical device/inode identity.
- Extracted the sole `PrimeExecutionKernel` from the previous session loop.
  P7 retains its single-use wrapper, exact launch limits and continuation prompt;
  the backend selects the reusable Pi lifecycle and retains cumulative callback
  counters. No second native-event loop, composer, or runner was created.
- Added `PrimeSessionBackend` with one mutation lock, detachable views, exact
  command digest/idempotency checks, durable public control events and suffix
  replay, host authority snapshot mirroring, cancellation, uncertain fencing,
  and idempotent owner cleanup.
- Added real `PrimeContextWitnessSession` integration: arm, concurrent native
  compact/proposal, reservation bound check, private witness/checkpoint fsync
  before ack, matching RPC terminal, and committed context receipt. Prompt and
  compact checkpoints retain `outstanding_effect` until the terminal/completion
  record is persisted; a successor checkpoint then clears it. A persisted
  definitive receipt is never replaced by a conflicting uncertain receipt.
- Generalized the runtime adapter to the private `run(request, signal)` protocol;
  exact `asterion.prime` manifest and `prime.tool.ipython` capability stay intact.

## Integration notes

- Construct an empty owned store, then the backend with exact identity, Pi
  launch material, `AsterionPrimeLimits`, token/cost caps, explicit `ModelPrice`,
  and a `PrimeToolExecutor` owner (`identity_sha256`, nonmutating
  `validate_lifecycle() -> object`, asynchronous `close`). Pi's
  preflighted extension remains the actual tool invocation path. Worker identity
  and opaque lifetime token are captured and revalidated before effects and
  clean recovery; missing, closed, or replaced resources reject execution.
- Identity command digest is SHA-256 of canonical JSON `list(command)`;
  ceilings digest is canonical `asdict(limits)` plus `aggregate_tokens` and
  `cost_micros`. All JSON digest encodings sort keys, omit whitespace and use UTF-8.
- Initialize `sync_authority_snapshot(budget, authority_revision=revision)` before
  effects. Subsequent snapshots may reuse that revision. These are mirrors;
  only `SessionContextManager` reserves/settles the host ledger. A reserved
  compact remains usable when the host's unreserved remaining tokens reach zero.
  Authority bookkeeping may still sync while execution is recovery-fenced.
- `attach(identity)` returns a `PrimeAttachment`; `close()` only detaches that
  view. Its `generation` is an attachment serial. Kernel/control-event generation
  remains `identity.generation`. `replay_events(after_cursor)` returns immutable
  wrappers with `.cursor` and `.event` (`ControlEvent`).
  New clean attachments reject with busy while an effect is active; they do not
  poison or interrupt that effect. Existing views retain snapshot/replay access.
- Prompt entry is `PrimePromptRequest(command_id, session_id, generation,
  input_text)`, with a finite 65536-byte private text cap. Receipts contain safe
  identity/digest/status only. Backend tracks its own expected durable position
  and rejects even a canonical unowned suffix before another attachment/effect.
- Context implements describe, compact and continuation resume. Unsupported
  context operations reject. Control supports create/attach/detach/pause/resume,
  cancel and checkpoint request; unrelated action/input routing is not invented.
  `session.create` system ID/version must match the selected application.
  A valid explicit create is mandatory before prompt/context operations. The
  Task 4 plan's short prompt examples omit lifecycle setup; they are pseudocode,
  not authorization to auto-create a goal/session. Create emits created→running;
  same-state pause/resume commands are durable no-ops without repeated events.
- Recovery validates an existing live owner. A new backend refuses a nonempty
  store; files alone never authorize recreating Pi or the worker.
- Minimal associated test update: `tests/test_asterion_prime_runtime.py` now
  accepts the narrow run protocol and rejects an object without that protocol.

## RED / GREEN evidence

Initial RED: `uv run python -m unittest -v tests.test_asterion_prime_backend
tests.test_asterion_prime_runtime` failed because the backend module did not
exist and the runtime still rejected the private run protocol. The parallel
store lane separately observed missing store/state RED before implementation.

Additional observed RED cycles covered write-failure redaction, attachment
serials, worker identity drift, fully reserved budget handling, unowned durable
suffixes, lifecycle checkpoint events, divergent cancellation, premature
checkpoint settlement, missing price/worker, invalid private prompt, and crossed
application identity. Each was rerun GREEN before final verification.

Final named verification (provider-free, 2026-09-10):

```text
uv run python -m unittest -v tests.test_asterion_prime_store tests.test_asterion_prime_backend tests.test_asterion_prime_session tests.test_prime_p7_native_installed tests.test_asterion_prime_runtime
PASS: 69 tests (Gate G3 plus runtime protocol regressions)

uv run ruff check src/asterion/agents/prime/{state,store,backend,execution,session}.py src/asterion/runtimes/asterion_prime.py tests/test_asterion_prime_{store,backend,runtime,session}.py
PASS
uv run ruff format --check <same files>
PASS: 10 files
uv run pyright src/asterion/agents/prime/{state,store,backend,execution,session}.py src/asterion/runtimes/asterion_prime.py
PASS: 0 errors, 0 warnings
git diff --check
PASS
```

The independent store/protocol review found the premature checkpoint settlement
issue above; it was fixed with two explicit RED/GREEN boundary tests. Existing
unrelated worktree changes were preserved; no docs/status files were edited.

## Important review repairs (2026-09-10)

Each of the seven reported issues was reproduced before its production fix.
The initial combined backend repair RED was 25 tests with 11 failures and 3
errors; focused worker lifetime tests subsequently also failed before repair.
An integration RED also caught active attach poisoning a normal prompt; the
fixed busy precondition rejects without mutation and preserves the effect owner.

| Review item | Observed RED | Implemented GREEN |
| --- | --- | --- |
| 1. Fixed Pi compact ordering | Genuine start/end/response fixtures produced uncertain instead of succeeded | Transport and the sole execution kernel validate exact manual start→end→response, request ID, contiguous native cursor and matching result; cursor advances atomically |
| 2. Rejected compact remained uncertain | Authenticated reject followed by failed RPC terminal poisoned reuse | Typed `PiRpcCompactResult.outcome` distinguishes completed/aborted; exact aborted terminal remains poisoned until the trusted backend supplies its independent matching rejection witness via `settle_rejected_compact(result)`; no exception-text inference |
| 3. Root/identity drift | Live chmod 0755 and same-inode, same-length identity rewrite were accepted | Every store trust read checks owner/0700/dev+ino and exact canonical identity bytes/hash; drift permanently poisons the store |
| 4. Recovery ignored live resources | Dead Pi attachment and closed/replaced worker lifetime were accepted | One recovery validator checks worker identity/token, launch/lease, reusable Pi child/token, owned store prefix and checkpoint; failures are fixed and fenced |
| 5. Mirrored budget ignored dimensions/deadline | Zero application/cost capacities dispatched; active prompt exceeded 20ms snapshot deadline | Application/aggregate/cost remaining and absolute snapshot deadline constrain dispatch and observed usage; open/prompt/compact obey the minimum deadline; backend only mirrors/limits, host alone debits its ledger |
| 6. Recovery OS errors exposed paths | Missing artifacts, stat/read errors and backend checkpoint OSError leaked sentinel paths | Store read/recovery errors normalize and poison; unified backend recovery raises a fixed error with no private exception context and fences |
| 7. Lifecycle was not reducible | Real reducer rejected repeated paused/running transitions | Backend reduces every event before persistence; explicit create required; legal state checks and same-state no-op prevent duplicate transitions |

The generic worker's new health check must not perform work or discover a new
owner. Task 6 must provide a stable opaque lifetime token and fixed failure on
closure/replacement. `PiRpcSession.validate_lifecycle(opened=...)` similarly
checks the exact live child and reusable idle lifecycle without restarting it.

Compaction's aborted flag alone is not proof of no mutation. Normal failures,
malformed/mismatched sequences, cancellation without independent authenticated
rejection, and approved-but-aborted compaction remain uncertain and fenced.
The settled rejected operation preserves the exact prior checkpoint and can
attach/resume/continue without replaying compaction.

Describe count evidence is intentionally narrow: `context_tokens` is the latest
authenticated post-compaction projection count, not a guessed model count or a
usage-token total. Initially, on prompt dispatch, and after uncertain effects it
is unavailable: describe returns definitive `rejected` with
`context-count-unavailable`, never a fabricated zero or stale compact count.
An exact duplicate describe command still returns its original durable receipt.

Additional controlled-process integration uses an actual `PiRpcSession`, a local
Python child speaking the fixed Pi 0.7.1 event contract, and the real authenticated
witness socket protocol. It checks prompt→compact→prompt and rejected compact→
attach→continuation resume→prompt on the same child and contiguous cursor. These
tests were added after the shared-worktree fix landed and first ran GREEN; their
RED evidence is the earlier kernel/transport reviewer reproductions, not a claim
that the controlled-process tests failed first. No external Pi model/provider is
invoked by this boundary test.

Repair verification (provider-free, 2026-09-10):

```text
uv run python -m unittest -q tests.test_asterion_prime_store tests.test_asterion_prime_backend tests.test_asterion_prime_backend_rpc tests.test_asterion_prime_session tests.test_prime_p7_native_installed tests.test_asterion_prime_runtime tests.test_pi_rpc_reusable tests.test_control_state tests.test_pi_session tests.test_dci_pi_rpc_recovery tests.test_dci_pi_rpc_proxy
PASS: 153 tests (G3, real child/witness integration, runtime, Pi reusable/one-shot, control reducer and proxy recovery)

uv run ruff check src/asterion/agents/prime/{state,store,backend,execution,session}.py src/asterion/runtimes/{asterion_prime,pi_rpc}.py tests/test_asterion_prime_{store,backend,backend_rpc,runtime,session}.py tests/test_pi_rpc_reusable.py
PASS
uv run ruff format --check <same files>
PASS: 13 files
uv run pyright src/asterion/agents/prime/{state,store,backend,execution,session}.py src/asterion/runtimes/{asterion_prime,pi_rpc}.py
PASS: 0 errors, 0 warnings
git diff --check
PASS
```

The bounded independent implementation re-review found no blocking Important
issues in the repaired backend/kernel/Pi contracts; the parent integration lane
will perform its own final review before advancing Tasks 5–9.

## Unfinished boundary

This proves the backend/store slice and existing installed P7 regression, not
native P1 acceptance. ControlHost/journal reconstruction wiring, provider/index
publication, application stage barriers, worker/oracle, operator cleanup-before-
terminal choreography, and bounded live acceptance remain Tasks 5–9. Native
prompt cost uses normalized input/output counts and injected price; compact
usage is reservation-charged, never claimed as observed provider usage. No live
provider request, full benchmark, full repository gate, or promotion gate was
run here. Pi-process/worker/operator-process crash resurrection is unsupported.
