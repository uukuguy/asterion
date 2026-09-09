# Task 5 report: application-owned persistent IPython extension

## Result

Implemented the P7-owned single-tool Pi extension and the Python application
host for one operator-injected restricted persistent IPython worker. No
provider, assembly, live-solving, `.env`, credential, ARC SDK, or Prime Agent
source wiring was added.

## RED evidence

- `npm --prefix packages/typescript/asterion-prime-extension test` failed with
  `TS18003` because `src/ipython-extension.ts` did not exist.
- `uv run python -m unittest -v tests.test_prime_p7_native_ipython` ran six
  initial contract tests and all failed with `ModuleNotFoundError` because
  `asterion.applications.prime.p7.ipython_host` did not exist.

## GREEN evidence

- `npm --prefix packages/typescript/asterion-prime-extension test`: 8 tests
  passed. The bridge success, mismatched-ID, and oversized-output cases run in
  a child Node process with the duplex socket inherited as FD 3.
- `uv run python -W error::ResourceWarning -m unittest -v
  tests.test_prime_p7_native_ipython tests.test_prime_ipython_host_orchestrator
  tests.test_prime_ipython_host_supervisor tests.test_prime_p7_solving_docker`:
  45 tests passed after the final added static detachment check (44 in the
  immediately preceding full transcript, plus the final focused check).
- `uv run ruff check src/asterion/applications/prime/p7/ipython_host.py
  tests/test_prime_p7_native_ipython.py`: passed.
- `uv run python -m py_compile
  src/asterion/applications/prime/p7/ipython_host.py
  tests/test_prime_p7_native_ipython.py`: passed.
- `uv run pyright src/asterion/applications/prime/p7/ipython_host.py
  tests/test_prime_p7_native_ipython.py`: 0 errors, 0 warnings.
- `git diff --check`: passed.

## Build artifact proof

- Output: `packages/typescript/asterion-prime-extension/dist/ipython-extension.mjs`
  (generated, intentionally ignored until Task 9 packages resources).
- Two consecutive builds produced the same SHA-256:
  `da68ee495916d54781b18e4b39633dbb53e5f9a2ba4164a312cccb10f65cf33f`.
- The artifact contains no `//` or `/*` comment token.
- Its only runtime imports are static `node:fs` and `node:util` imports.
- The Node suite loads the exact artifact bytes through
  `asterion_pi_extension_loader.mjs` using source FD/name/SHA-256 metadata.
- The Python suite admits the artifact through `PiExtensionBinding.preflight()`
  and `PiExtensionLease.validate_launch()`.

## Files

- `packages/typescript/asterion-prime-extension/package.json`
- `packages/typescript/asterion-prime-extension/tsconfig.json`
- `packages/typescript/asterion-prime-extension/src/ipython-extension.ts`
- `packages/typescript/asterion-prime-extension/test/ipython-extension.test.mjs`
- `src/asterion/applications/prime/p7/ipython_host.py`
- `tests/test_prime_p7_native_ipython.py`

The generated `dist/ipython-extension.mjs` is not staged because root
`.gitignore` intentionally excludes all `dist/` directories.

## Contract notes

- The Node bridge writes one exact JSONL execute request and accepts one exact
  matching result. It validates IDs, exact keys, UTF-8, code/line/output caps,
  deadlines, duplicate IDs, concurrent use, and abort signals. Any failure is
  normalized to one body-free error; post-dispatch failures poison and close
  the descriptor.
- `PersistentIpythonHost` serializes cells through one worker instance, so
  namespace state survives across cells. It returns immutable
  `PrimeToolResult` values with the submitted call ID.
- The sealed worker-visible facade offers only `observe()`, `status()`, and
  `act(actions)`. For the process implementation, exact client-module bytes are
  AST-checked for those public bindings before injection.
- The production factory concretely adapts an operator-injected restricted P7
  worker implementing the established `acquire`/`execute_cell`/`cleanup`
  lifecycle. It does not import the legacy `prime_agent` product namespace.
- Cancellation before dispatch is a certain error. Timeout, cancellation,
  worker loss, malformed post-dispatch results, oversized successful output,
  or a worker-reported cell failure from the established adapter are uncertain
  effects; the host latches loss and runs bounded cleanup.

## Existing orchestrator/supervisor decision

No existing files were edited. The inspected modules are P1-specific
completion-attestation code: fixed starter/source/oracle digests, snapshot
ordering, broker revocation, and cleanup absence. They are not a reusable
persistent-cell transport. Composition through the narrow worker lifecycle
preserves their regression behavior without importing P1 authority into P7.

## Self-review

An independent review reported no critical findings, two high findings, and
one medium finding.

- Fixed high: removed the direct legacy `prime_agent` production import and
  added a static detachment assertion.
- Fixed high: bounded cancellation-resistant task reaping and added a worker
  that suppresses `CancelledError` to prove the host still cleans up and
  returns.
- Accepted phase boundary: the built `dist/` artifact is not yet wheel package
  data. Task 9 explicitly owns build-before-Hatch and installed-artifact
  packaging; Task 5 proves the generated artifact through the real loader and
  binding contracts.

## Concerns

- Task 8 must supply the concrete restricted worker and bridge FD only after
  operator preflight. Task 5 deliberately does not choose Docker paths,
  credentials, model configuration, provider, assembly, or live game wiring.
- Task 9 must make the deterministic `.mjs` a packaged resource before an
  installed-wheel claim is possible.
