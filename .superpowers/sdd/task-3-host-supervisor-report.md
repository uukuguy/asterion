# Task 3 host-supervisor slice report

## Scope delivered

- Added `ipython_host_supervisor.py`, a pure host-only P1 reduction module.
- Added focused provider-free unit tests in `test_prime_ipython_host_supervisor.py`.
- No Docker transport, launcher, worker, provider, generic framework, existing
  test, or documentation files were changed.

## Trust boundary

`inspect_answer_source()` bounds input to 16 KiB and parses bytes as syntax
only. It admits only a sole `answer` function with zero arguments and a direct
integer return value of `42`; it does not load or run inspected code.

`mint_ipython_host_completion()` admits only `IpythonHostCompletionInputs`.
Its input surface intentionally has no stdout, stderr, exit status, frame, or
other worker-output field. PASS requires a revoked one-call bounded-model
receipt with positive I/O, valid identities and digests, its cell digest equal
to the successful host oracle and daemon post-snapshot digest, exactly the
`("ipython",)` tool set, a locked changed pre-snapshot, verified cleanup, and
verified absence. The returned projection contains only `PASS` and an evidence
digest; private source/cell/prompt values have redacted representations.

## TDD evidence

The first focused test invocation was RED with the expected
`ModuleNotFoundError` for the new supervisor module. A later test change
exposed that `True == 1` could otherwise pass the one-call condition; the test
was RED, then the reducer was tightened to require an exact integer.

## Fresh verification

```text
uv run python -m unittest -v tests.test_prime_ipython_host_supervisor
Ran 4 tests ... OK

uv run ruff check src/asterion/applications/prime_agent/operator/ipython_host_supervisor.py tests/test_prime_ipython_host_supervisor.py
All checks passed!

pyright src/asterion/applications/prime_agent/operator/ipython_host_supervisor.py tests/test_prime_ipython_host_supervisor.py
0 errors, 0 warnings, 0 informations
```

## Remaining integration concern

This is deliberately a pure reduction slice. The later Docker/host integration
must create these facts only from daemon-attested snapshots and the real host
broker receipt, and must not translate worker terminal output into them.

## Review-fix follow-up (2026-09-05)

Replaced public generic receipt/snapshot/input dataclasses and direct minting
with `IpythonHostSupervisor`, a per-instance ordered state machine. The public
completion constructor requires a module-private seal; snapshots, brokered-cell
receipts, and AST observations are private, issuer-bound attestations produced
only through private application-host adapter hooks. This is an
application-host boundary in Python, not cryptographic isolation from code
already running in that host process.

The supervisor binds fixed assembly/package/implementation/image/workload/oracle
identity and requires: failed initial AST, one non-cancelled brokered `ipython`
cell, changed regular-file post snapshot, broker revocation, cleanup and
absence, then final AST success. Cell and final source digests are separate.
Versioned evidence covers identity, model/cell digests, counts, tools,
snapshot/AST booleans, cleanup/revocation booleans, and ordered stages.

The oracle checks byte limits before hashing in attestation paths, strictly
decodes UTF-8 before `ast.parse`, and never compiles, imports, or executes
source. Malformed and hostile-equality inputs use the same body-free error.

### TDD evidence

Replacement tests were written first; their first invocation was RED with the
expected missing `IpythonHostExpectedIdentity` import. A subsequent
digest-separation assertion initially failed because the test cell was byte
identical to final source; the fixture was then made distinct while valid.

### Fresh verification

```text
uv run python -m unittest -v tests.test_prime_ipython_host_supervisor
Ran 9 tests ... OK

uv run ruff check src/asterion/applications/prime_agent/operator/ipython_host_supervisor.py tests/test_prime_ipython_host_supervisor.py
All checks passed!

pyright src/asterion/applications/prime_agent/operator/ipython_host_supervisor.py tests/test_prime_ipython_host_supervisor.py
0 errors, 0 warnings, 0 informations
```
