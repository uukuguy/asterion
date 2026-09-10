# Native P1 Task 6 — restricted worker, fixture, oracle, receipt

## Delivered boundary

- Added the provider-owned `P1WorkerProcess`, fixed installed `worker_main.py`,
  private immutable worker values, deterministic input/task statement, read-only
  oracle, and safe native receipt chain under
  `src/asterion/applications/prime/p1/`.
- One direct-argv `subprocess.Popen` uses an explicitly selected interpreter,
  isolated Python flags, locale/encoding-only environment, exact temporary cwd,
  and inherited root directory FD. Interpreter/entry-point fingerprints and the
  directory identity are rechecked before use. The worker uses real IPython;
  its profile remains beneath the worker root and history persistence is off.
- `validate_lifecycle()` observes the same live Popen owner, PID, directory,
  executable bindings, deadline, and poison state without reaping. Its opaque
  object token is stable. Closing or replacing the process owner fails health
  validation; there is no automatic restart or effect replay.
- Bounded private JSONL carries exact request/turn IDs. Calls are sequential,
  capped at four, with 16,384 code bytes and 65,536 output bytes. One absolute
  deadline covers startup and cells. Any failure after possible dispatch poisons
  the worker, terminates its process group, closes streams, and reaps it once.
  Cleanup is idempotent; retry after directory cleanup failure does not reap a
  second time. Cancellation messages and exception chains are redacted.
- Only `input_tuple` and `task_statement` are seeded. The statement specifies
  the task but contains neither a seeded class implementation nor final answer.
  Allowlisted imports/builtins, AST restrictions, descriptor-relative file
  opening, and execution-time auditing reject external files, symlinks, system
  imports, environment access, subprocess/network/native-library operations,
  and dynamic introspection channels covered by the boundary tests. Caught
  denials and caught output overflow still poison the worker.
- Host snapshots combine trusted worker observations with exact file bytes read
  by the parent through its directory FD. Recorded evidence includes creation
  nonce/PID identity, code digests, class and isolated callable behavior probes,
  original object IDs, actual cell calls, actual read-byte digests, verification
  record, final result, initial seed inventory, and denial counts. Behavior
  probes run against a copied instance with narrow globals and do not mutate
  the live model object or add a model cell.
- The oracle binds to one worker and initial kernel generation, independently
  computes expected values, and requires distinct setup and verification turns,
  a trusted compact/reconstruction checkpoint, and a continuation using the
  same identity/object/file bytes. Snapshots and issued receipts cannot be
  replaced with self-reported/model-produced evidence. Safe receipt projections
  bind the stage, checkpoint, compact, oracle, and cleanup digests.

## Dependency decision

The controller authorized the necessary `pyproject.toml` and `uv.lock` edits.
The `prime` extra now includes `ipython>=8.37,<10`: the project still supports
Python 3.10, while IPython 9 requires newer Python. The generated lock selects
IPython 8.39.0 for Python 3.10 and IPython 9.17.1 for Python 3.11+. Current focused
verification initially ran on Python 3.14 with locked IPython 9.17.1. The formal
review correction below adds actual installed-wheel Python 3.10/3.11/3.12/3.14
verification. Runtime code never installs packages.

## Initial implementation RED / GREEN evidence (commit 99638af6)

- Initial worker contract test failed with `AssertionError: unexpectedly None`
  because the P1 module did not exist. Initial oracle/receipt contract assertions
  independently failed for their missing modules.
- Actual subsequent RED failures covered caught audit denial, caught output
  overflow, private-attribute access through formatting and pattern matching,
  IPython profile outside the worker root, cleanup error/cancellation redaction,
  unsafe receipt fields, initial kernel-generation mismatch, and setup without
  the required real accumulator call. Each was changed and rerun GREEN.
- Independent review reproduced a real evidence gap: `read(0)` counted as a
  file read and could satisfy stage two. Actual-read SHA-256 evidence now rejects
  empty, partial, and EOF reads in both verification and continuation. All six
  regression scenarios failed before the oracle change and passed afterwards.
- Final command:
  `uv run --extra prime python -W error::ResourceWarning -m unittest -v tests.test_asterion_prime_p1_worker tests.test_asterion_prime_p1_oracle`
  — **32 tests PASS**, 6.357 seconds; zero skipped tests.
- `uv run --extra prime ruff check src/asterion/applications/prime/p1 tests/test_asterion_prime_p1_worker.py tests/test_asterion_prime_p1_oracle.py`
  — PASS.
- Same paths with `ruff format --check` — PASS, nine files already formatted.
- Same paths with `pyright` — zero errors and warnings. The CLI separately prints
  an available-tool-version notice, which is not a code diagnostic.
- `uv lock --check` and `git diff --check` — PASS.
- Process inspection after the completed suites found no Python invocation of
  this task's `-I -B -u .../p1/worker_main.py`. Tests assert absent process IDs,
  closed streams, removed exact temporary roots, and one reap after normal,
  failed, deadline, and cancellation paths. Independent review probe workers
  were also closed.

## Review and remaining integration

An Astra sub-agent implemented the oracle/receipt files and separately reviewed
the worker lifecycle/instrumentation it did not implement. The reproduced
read-byte issue was fixed; no further ordinary functional gap was reproduced
in that review. This is a restricted Python execution boundary, **not an OS
security sandbox**. It does not claim complete isolation against arbitrary
CPython exploitation. `ControlledExecutorService` was neither changed nor
presented as the interactive execution owner.

Task 7/operator integration must start the worker after preflight, supply actual
admitted turn IDs, bind the same worker to the backend and oracle, and call
`mark_compact_checkpoint()` with the actual sealed compact/reconstruction
identities. These fields are operator observations, not worker/model inputs.
`P1Oracle(worker, kernel_generation=...)` binds the real initial generation.
`P1WorkerProcess.close()` returns its exact cached cleanup receipt; a narrow
adapter may be needed for the backend protocol's `close() -> None` annotation.

`seal_cleanup_receipt()` accepts external cleanup bits only from operator-owned
resource observations. `backend_closed` must represent the backend's complete
cleanup result, and `extension_closed` must include the witness channel/FD
cleanup. No model-supplied flags qualify. The actual worker close receipt is
checked by object identity and its final effect digest.

Full `make check`, `make promotion-check`, actual Pi compaction/control
reconstruction, and bounded live P1 acceptance are **not rerun in Task 6** and
remain controller-owned integration gates. The installed-worker wheel boundary
is now verified below; this is not installed-application acceptance. The scripted
test cells prove worker/oracle behavior only; they are not live model evidence,
and this task does not claim full native P1 acceptance or promotion.

Only Task 6 files, its report, the explicitly approved dependency/lock edits,
and the subsequently approved minimal compatibility changes below are included
in this task's commits. Other agents' changes are preserved.

## Formal-review correction — four Important findings

1. **Same-content file rewrites.** Three new oracle regressions actually failed
   before the fix: continuation rewriting identical bytes, verification doing
   the same through `./stage-one.json`, and parent-side replacement with another
   inode holding the same bytes. Trusted instrumentation now records target-file
   write calls, accepted bytes, and write-mode opens per cell, including handles
   retained across cells. The parent reads bytes and `(st_dev, st_ino)` from the
   same FD opened beneath its held root FD. The oracle requires setup writes,
   zero later writes/write opens, and unchanged inode identity and exact bytes.
   These private observations are included in the evidence digest, not exposed
   as public file paths, contents, or raw inode values.
2. **Portable non-reaping lifecycle.** Missing/unavailable `os.waitid` probes
   reproduced lifecycle rejection on macOS. The host now registers a kqueue
   process-exit observer on its exact owned child before readiness on macOS/BSD;
   supported other platforms retain `waitid(..., WNOWAIT)`. Health observation
   does not call Popen poll/wait or waitpid. Exit events and stdout EOF are
   latched; close owns reap. Missing all supported primitives rejects before
   process creation. Registration failure closes its observer, terminates/reaps
   the child, and removes its root. Tests also kill a live child into an unreaped
   exit and verify unchanged Popen returncode/reap count until explicit cleanup,
   then one reap, closed observer/pipes, removed root, and idempotent close.
3. **Actual Python 3.10 import chain.** The first interpreter import failed on
   `importlib.resources.abc`; subsequent real worker imports identified the same
   `Traversable` import in payload/author, `typing.Never` in recorder, and
   `typing.Self` in benchmark process. The controller approved each minimal
   change individually: Python 3.10 uses `importlib.abc.Traversable` in
   `capability_packages/{model,payload}.py` and `capability_sdk/author.py`;
   `pathlight/recorder.py` uses annotation-only `NoReturn`; benchmark process
   uses a version-conditional bound TypeVar with `cls: type[Self]` to retain
   subclass-return typing. Package/worker imports are regression-tested in real
   Python 3.10 subprocesses. No unentered control/DCI modules were rewritten.
4. **Bounded root writes.** Four new tests actually failed before implementation:
   a 200,000-byte write, per-call/per-cell boundaries, aggregate cross-cell root
   bytes, and UTF-8 multibyte accounting. Accepted writes are limited to 4,096
   bytes per call, 16,384 bytes per cell, and 32,768 logical regular-file bytes
   under the root, including IPython's initialized profile files. There is also
   a 32-regular-file count limit. The worker uses descriptor-relative root
   accounting, checks prospective byte growth before writing, flushes each
   accepted write, and charges repeated overwrites against the cell budget.
   Over-limit attempts increment audit denials; even caught denial yields an
   uncertain cell, poisons the worker, and reaps it. Tests cover exact inclusive
   boundaries followed by one-byte overflow. UTF-8 is the only text encoding.

All seven new worker/oracle regressions were RED before their changes and GREEN
afterwards; together with the six portability tests, the original 32 become 45.
The first `uv run python -m unittest -v
tests.test_asterion_prime_p1_portability` run had three failures: the actual
Python 3.10 import plus live-worker rejection for missing and unavailable
waitid. Subsequent `PYTHONPATH=src <py310>/bin/python -m unittest -v
tests.test_asterion_prime_p1_portability` runs exposed each approved import-chain
failure above. Additional lifecycle RED observations were failure to reject
absent observation primitives and macOS zombie `killpg` raising EPERM before
cleanup/reap; their regression cases now pass.

### Cancellation interpreter evidence

A standalone coroutine (no Asterion imports) catches cancellation, leaves its
exception handler, then raises a fresh empty `CancelledError()`. After
`task.cancel('probe-private-cancellation-value')`, awaiting that task on CPython
3.10.17 yields two linked empty `CancelledError` objects; 3.14.3 yields one.
Local `asyncio.futures._PyFuture._make_cancelled_error` confirms 3.10 attaches
the saved cancellation as context. Thus a universal `__context__ is None`
assertion would misstate interpreter behavior. With controller approval, the
regression traverses both context/cause links, requires at most two distinct
CancelledError objects with empty args, no notes, and no sentinel, and retains
the stronger None context/cause assertions on 3.11+. Cancellation propagation
is unchanged and is never converted into a success result.

### Final verification and package matrix

- Ordinary lock environment:
  `uv run --extra prime python -W error::ResourceWarning -m unittest -v tests.test_asterion_prime_p1_worker tests.test_asterion_prime_p1_oracle tests.test_asterion_prime_p1_portability`
  — **45 PASS**, 7.888 seconds, no skips.
- Approved compatibility surface regression:
  `uv run --extra prime python -m unittest -v tests.test_capability_package_model tests.test_capability_package_payload tests.test_capability_sdk tests.test_pathlight_recorder tests.test_benchmark_process`
  — **56 PASS**, 3.519 seconds.
- `uv build --wheel --out-dir /tmp/asterion-p1-task6-wheel.HtZs0N` — PASS.
  Wheel SHA-256:
  `c03fe555c3ee4d507a5ff337f655a8c576f14386e6a6e24e881a334f348e4e81`.
  ZIP inspection confirms all seven P1 modules, `Requires-Python: >=3.10`, and
  the bounded optional IPython requirement.
- Installed the wheel using `uv pip install --python <matrix-python> --no-deps
  --reinstall <wheel>` in four independent environments, then ran the same
  three-module suite using `<matrix-python> -I -W error::ResourceWarning`.
  Before adding the repository root solely for the tests package, each process
  imported the host and asserted its path contains `site-packages`; worker
  execution consequently uses the installed fixed entrypoint, not editable
  source or a test-provided worker. Python 3.10 import-only regression
  subprocesses separately exercise the checked-out public import chain.

| macOS interpreter | IPython | Installed-wheel result |
| --- | --- | --- |
| CPython 3.10.17 | 8.39.0 | 45 PASS, 13.197 s, zero skips |
| CPython 3.11.14 | 9.17.1 | 45 PASS, 6.996 s, zero skips |
| CPython 3.12.12 | 9.17.1 | 45 PASS, 8.744 s, zero skips |
| CPython 3.14.3 | 9.17.1 | 45 PASS, 7.951 s, zero skips |

- Ruff check: all seven P1 modules, three P1 test modules, and five approved
  compatibility files PASS. Ruff format check: the ten P1 source/test files
  plus model/author PASS (12 files). Existing formatting differences in
  benchmark process, payload, and recorder were reproduced directly from
  `git show HEAD:<path> | ruff format --diff --stdin-filename <path> -` and left
  unchanged to preserve the authorized minimal compatibility scope.
- Pyright: P1 source/tests plus benchmark process/model/payload/author PASS,
  zero errors and warnings. Explicitly checking recorder reports three existing
  diagnostics (Protocol return body, snapshot return type, list.sort override);
  checking an exact original-HEAD copy reproduces all three. No new recorder
  type diagnostic was introduced. The whole modified-file Pyright surface is
  therefore **not reported as PASS**.
- `uv lock --check` and `git diff --check` PASS. No dependency change was needed
  beyond the previously approved lock. Linux's WNOWAIT branch is **not rerun**;
  the actual multi-interpreter matrix above is macOS, not all-platform evidence.

Tests assert process absence, one reap, closed streams/observer descriptors, and
removed exact worker roots for normal/failure/cancellation/denial paths. Final
process inspection after these suites found no `-I -B -u .../p1/worker_main.py`
processes. Isolated interpreter environments and the built wheel are retained
as review artifacts; they are not active worker roots. No live provider work,
OS sandbox claim, ControlledExecutor rewrite, or application acceptance claim
is included in this correction.
