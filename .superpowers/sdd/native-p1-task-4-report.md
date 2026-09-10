# Native P1 Task 4: shared backend and durable store

Implementation commit: the commit containing this report, subject
`feat: add shared prime session backend`.

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
  and a `PrimeToolExecutor` owner (`identity_sha256`, asynchronous `close`). Pi's
  preflighted extension remains the actual tool invocation path. Worker identity
  is revalidated before effects; missing worker or price rejects execution.
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
- Prompt entry is `PrimePromptRequest(command_id, session_id, generation,
  input_text)`, with a finite 65536-byte private text cap. Receipts contain safe
  identity/digest/status only. Backend tracks its own expected durable position
  and rejects even a canonical unowned suffix before another attachment/effect.
- Context implements describe, compact and continuation resume. Unsupported
  context operations reject. Control supports create/attach/detach/pause/resume,
  cancel and checkpoint request; unrelated action/input routing is not invented.
  `session.create` system ID/version must match the selected application.
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

## Unfinished boundary

This proves the backend/store slice and existing installed P7 regression, not
native P1 acceptance. ControlHost/journal reconstruction wiring, provider/index
publication, application stage barriers, worker/oracle, operator cleanup-before-
terminal choreography, and bounded live acceptance remain Tasks 5–9. Native
prompt cost uses normalized input/output counts and injected price; compact
usage is reservation-charged, never claimed as observed provider usage. No live
provider request, full benchmark, full repository gate, or promotion gate was
run here. Pi-process/worker/operator-process crash resurrection is unsupported.
