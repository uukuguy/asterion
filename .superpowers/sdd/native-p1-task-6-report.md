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
verification ran on Python 3.14 with locked IPython 9.17.1. Python 3.10 itself was
not rerun. Runtime code never installs packages.

## RED / GREEN evidence

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

Full `make check`, installed-wheel verification, `make promotion-check`, actual
Pi compaction/control reconstruction, and bounded live P1 acceptance are **not
rerun in Task 6** and remain controller-owned integration gates. The scripted
test cells prove worker/oracle behavior only; they are not live model evidence,
and this task does not claim full native P1 acceptance or promotion.

Only Task 6 files, its report, and the explicitly approved dependency/lock edits
are included in this task's commit. Other agents' changes are preserved.
