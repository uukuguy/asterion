# Native P1 Task 7 — exact package, assembly, and runtime dispatch

## Delivered boundary

- Published `prime-ipython-coding-native@1.0.0` as one explicit builtin
  capability package with executable capability
  `prime.ipython-coding@1.0.0`. Its implementation accepts only the literal
  `fixed-small-verification` preset and projects only the safe native receipt
  digest.
- Added the exact `prime.ipython-coding@1.0.0` assembly over runtime
  `asterion.prime` and the sorted host capability set `prime.ipython`,
  `prime.p1-oracle`, `prime.pi-extension`, `prime.private-trace`, and
  `prime.session-backend`. The closed JSON contains compatibility metadata only.
- Extended `prime-applications` with sorted P7 and P1 metadata while retaining
  exactly one `asterion.prime` runtime factory binding. The common factory now
  dispatches by exact application ID/version; unknown keys fail closed.
  Existing P7 construction moved intact behind `build_p7_runtime`.
- Migrated only the public P1 application-index entry to
  `asterion.applications.prime:create_provider`. The explicit legacy
  `prime-agent` provider, its P1 metadata, and existing legacy host-service
  entries remain installed and do not create automatic selection ambiguity.
- Defined a narrow Task-8-implementable `P1RuntimeHost` barrier contract. The
  runtime itself owns stage-one/stage-two order, digest/usage validation,
  budget/recovery/cancellation classification, execution-stopped reporting,
  cleanup-gated finalization, and the public event state machine. Success emits
  exactly one receipt artifact followed by `run.completed`; missing
  finalization is a protocol failure and cannot synthesize a terminal.
- Added `P1WorkerOwnerAdapter`, which captures and revalidates Task 6's exact
  live-owner token and retains the identical `P1WorkerCleanupReceipt` returned
  by worker close while presenting the backend's `close() -> None` shape.

This task does not import or implement `ControlHost`, the Task 8 coordinator,
operator preflight, or live provider execution.

## TDD evidence

Initial metadata/selection/installed-wheel RED:

```text
uv run python -m unittest -v tests.test_asterion_prime_p1_provider \
  tests.test_asterion_prime_p1_runtime tests.test_asterion_prime_p1_installed
FAIL: missing create_prime_ipython_coding_native_package,
      missing asterion.applications.prime.p1.runtime_binding,
      and missing wheel resources
```

Subsequent focused RED/GREEN cycles proved:

- immutable fixed P1 runtime options and constructor-time injection of all four
  peer host services into the aggregate barrier validator;
- rejection of a format-invalid worker identity while preserving the stable
  lifecycle token and original cleanup receipt;
- the real capability implementation's async event collection. Its new test
  first failed with `TypeError: 'async_generator' object is not an iterator`,
  then passed after the implementation used an async comprehension.
- cleanup-gated terminal projection. The new regression first observed a
  synthetic recovery terminal after private finalization failure; the fixed
  runtime now raises the redacted `P1 runtime finalization failed` protocol
  error without emitting a terminal.
- cancellation after committed usage. The regression first observed
  `CapabilityExecutionError` for the valid
  `run.started → usage.reported → run.completed(cancelled)` stream; the
  capability now validates the complete stream, ignores validated usage for
  terminal shape, and preserves cancellation.
- cumulative token enforcement. The regression first failed because the
  compact reservation was absent from the stage-two release contract; after
  the contract and runtime fix, both stage usages plus the conservative compact
  reservation share the fixed `64000` ceiling and excess maps to
  `p1_budget_limited`.

Final focused and P7 regression command:

```text
uv run python -m unittest -v \
  tests.test_asterion_prime_p1_provider \
  tests.test_asterion_prime_p1_runtime \
  tests.test_asterion_prime_p1_installed \
  tests.test_prime_application_provider \
  tests.test_application_discovery \
  tests.test_prime_p7_native_installed \
  tests.test_prime_p7_native_provider
PASS: 46 tests
```

The two existing P7 composition tests and the installed P7 script now supply
both packages required by the expanded provider closure, but still select and
execute only P7. Their P7 assertions remain unchanged.

## Packaging and static verification

```text
uv build --wheel --out-dir /tmp/asterion-native-p1-task7-wheel.7ceD2w
PASS: asterion-0.1.0-py3-none-any.whl
SHA-256: a7e83347d22fa4d26d83b40b2ef5a4c61501e436ec0393b84c9eaefa4493a8ec
```

ZIP inspection confirmed the P1 assembly, package `__init__`, provider, host,
package manifest, capability manifest, and entry-points metadata. The installed
test built and installed a fresh wheel into an isolated venv, ran Python with
`-I`, resolved P1 to `prime-applications`, found all three JSON resources, and
confirmed no `asterion.applications.prime_agent` module was imported. The same
wheel retained the explicit legacy provider and host-service entries.

```text
uv run ruff check <Task 7 production/tests plus approved migration tests>
PASS
uv run ruff format --check <Task 7 new and modified production/new-test files>
PASS
uv run pyright <Task 7 production and three new tests>
PASS: 0 errors, 0 warnings
uv lock --check
PASS
git diff --check
PASS
```

The pre-existing `tests/test_builtin_capability_source.py` registration snapshot
was already stale against the committed P7 builtin registration and also expects
conformance absent from the committed P7 package. An extra exploratory run
therefore failed for both committed P7 and newly added P1. It is outside the
Task 7 planned gate and was not rewritten or reported as passing.

## Promotion boundary

`make promotion-check` exited nonzero at the existing external boundary:

```text
promotion check failed: external Prime source binding could not be created
```

This is **External-limited**, not PASS. Provider-free package/resource and
installed-wheel checks above passed; no live provider request or native P1
acceptance was run. Task 8 still owns coordinator choreography and provider-free
closed-loop integration.

## Independent review

The independent read-only review first found the post-stage-one cancellation
and cumulative-token defects recorded in the TDD section. After their RED/GREEN
repairs, the reviewer reran the focused 15 tests plus Ruff and Pyright and
returned **APPROVED**, with no remaining Critical or Important findings.
