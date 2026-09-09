# Asterion-prime P7 Task 8 report

## Result

Published the metadata-only `prime-applications` provider for
`prime.arc-agi-3-solving@1.0.0`, selecting only the peer runtime
`asterion.prime`. The exact application assembly declares the existing
`prime-arc-agi-3-solver@1.0.0` package, its one application capability, and the
four sorted injected host capabilities. It contains no executable or private
operator data.

The provider-owned runtime factory consumes an immutable, redacted
`PreflightedPrimeLaunch` containing the exact host-acquired `PiRpcSession`,
`PiExtensionBinding`, open `PiExtensionLease`, and approved full command. It
requires the exact preflighted `PersistentIpythonHost`, initial fixed
`ArcBroker`, and unsealed `PrimeTraceRecorder`. It performs no discovery,
preflight, authorization, acquisition, retry, or persistence. A rejected
configuration closes an unhanded extension lease; successful construction
transfers lease ownership to `AsterionPrimeSession` and returns
`AsterionPrimeRuntimeClient`.

The operator boundary accepts already-resolved environment values, admits only
the exact DeepSeek V4 Flash host, and returns immutable fixed options for 500
actions, 128 callbacks, and 3,600,000 ms. It does not read `.env` inside
framework/runtime code and exposes no tuning knobs or credentials. The solve
prompt is game-agnostic and directs inspection, explicit hypotheses, short
experiments, before/after comparison, rejection of no-ops/deaths, and replanning
until one completed level or the fixed limit.

## Plan correction

The literal Task 4/Task 8 example advertised both
`prime.arc-agi-3-solving` and `prime.tool.ipython` from the runtime. Real
composition proved that this conflicts with the package manifest, which owns
and provides `prime.arc-agi-3-solving`; the composition graph correctly failed
closed on two providers for one capability. With task-owner approval, the
runtime manifest and provider binding now advertise only the runtime-owned
`prime.tool.ipython`. The application package remains the sole owner of
`prime.arc-agi-3-solving`. No generic composition rule was changed.

## TDD evidence

Initial missing-provider RED:

```text
uv run python -m unittest -v tests.test_prime_p7_native_provider
ImportError: cannot import name 'create_provider' from
'asterion.applications.prime'
Ran 1 test; FAILED (errors=1)
```

Composition correction RED:

```text
uv run python -m unittest -v \
  tests.test_prime_p7_native_provider.TestPrimeP7NativeProvider.test_p7_application_composes_package_over_runtime_tool_capability
ApplicationProviderError: installed application composition closure is invalid
Ran 1 test; FAILED (errors=1)
```

The underlying direct resolver reported `CapabilityCompositionError:
capability provider is ambiguous`. After narrowing runtime capability ownership,
the exact provider/package/assembly composition regression passed.

Required combined provider/discovery GREEN:

```text
uv run python -m unittest -v \
  tests.test_prime_p7_native_provider tests.test_application_discovery \
  tests.test_application_selection tests.test_installed_application_provider
Ran 36 tests in 0.047s
OK
```

Final affected runtime/provider/detachment GREEN:

```text
uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_prime_p7_native_provider tests.test_asterion_prime_session \
  tests.test_asterion_prime_runtime tests.test_asterion_prime_architecture
Ran 41 tests in 0.103s
OK
```

Static verification:

```text
uv run ruff check <Task 4 capability correction and Task 8 source/tests>
All checks passed!

uv run python -m py_compile <Task 4 capability correction and Task 8 source/tests>
exit 0

uv run pyright <Task 4 capability correction and Task 8 source/tests>
0 errors, 0 warnings, 0 informations

make docs-check
checked 196 markdown files, 57 local links

git diff --check -- <Task 4 capability correction and Task 8 files>
exit 0
```

`make promotion-check` was attempted but did not reach project/package checks:
the current Make configuration supplied an empty `--npm-cache`, and the checker
returned `declared npm cache is invalid`. No network, provider, model, worker,
or live puzzle operation occurred. Per task-owner direction this packaging gate
is external-config-limited and deferred to Task 9; it is not reported as PASS.

## Self-review and boundary

- Provider listing and application-index selection stay metadata-only; only the
  explicitly selected provider entry point is loaded.
- All provider, application, package, capability, runtime, and host-capability
  identities are exact; assembly arrays are closed, sorted, and unique.
- Runtime options are copied by `RuntimeFactoryContext` into a redacted immutable
  mapping and must equal the fixed operator preset.
- Factory error messages and operator errors are content-free; reprs do not
  expose commands, paths, credentials, provider payloads, or trace bodies.
- The detachment gate passes and the new path imports no legacy Prime Agent
  source, SDK, gateway, source lock, or wrapper provider.
- This task publishes and composes the injected native seam. It does not run a
  live model, register/acquire the later live host-service factories, prove an
  installed-wheel execution, or claim that one ARC level has been solved.

## Focused execution-blocker correction

Review found that the shared solver implementation still admitted only the
legacy `prime.agent` preset and that the operator exposed options without
constructing the assembly's four host services. The package now requires
`asterion.prime` with only `prime.tool.ipython`, rejects the retired fixed input,
and forwards the application-supplied `P7_SOLVE_PROMPT` unchanged through the
normal `RunRequest`. Receipt access uses the assembly-declared private-trace
boundary; there is no legacy provider, gateway, source-tree, seeded-action, or
answer fallback.

The operator now accepts only injected external edges and returns immutable,
redacted `P7OperatorResources`. It creates the fixed ARC broker and persistent
IPython host, a private unsealed trace recorder, and pinned Pi extension launch
material with the exact DeepSeek provider/model command and approved process
environment. The owned duplex bridge connects the compiled extension FD to the
Python IPython host without starting the worker until a tool call. Pi process
startup remains lazy in `PiRpcSession`. Partial construction closes sockets,
trace descriptors, and any acquired extension lease; the returned cleanup
handle boundedly closes the bridge/worker and remaining resources.

Focused correction TDD:

```text
native package RED: CapabilityExecutionError: Prime solver runtime is unavailable
operator RED: ImportError: cannot import name 'build_p7_operator_resources'

uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_prime_arc_agi_3_solver_package tests.test_prime_p7_native_provider \
  tests.test_asterion_prime_session tests.test_asterion_prime_runtime \
  tests.test_asterion_prime_architecture
Ran 46 tests in 0.119s
OK

uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_prime_p7_native_broker
Ran 8 tests in 0.109s
OK

uv run ruff check <focused correction source/tests>
All checks passed!

uv run python -m py_compile <focused correction source/tests>
exit 0

uv run pyright <focused correction source/tests>
0 errors, 0 warnings, 0 informations
```

Provider listing remains metadata-only: the end-to-end composition test observes
zero worker starts and zero Pi process starts through provider selection,
package/plan composition, host preflight, and runtime factory construction.
`make promotion-check` was not rerun, per task-owner direction; its previously
recorded external configuration limitation remains deferred to Task 9.

## Final prompt and receipt boundary correction

The capability package now admits exactly the application-authored prompt by a
domain-separated SHA-256 contract. The prompt remains owned by
`applications/prime/p7/prompt.py`; the package imports no application module,
and the digest is not published in either manifest. Arbitrary, legacy-preset,
and seeded-answer-like inputs are rejected before the runtime is called.

The `prime.private-trace` service is now an application-owned immutable,
redacted `P7PrivateTraceReceipt` adapter rather than a raw recorder. It binds
the exact broker and recorder, exposes only the typed recorder property needed
by runtime validation, and implements the package receipt-accessor protocol.
After one terminal level transition it derives the content-safe score/receipt,
checks the requested digest, appends terminal replay evidence, and seals once.
Early, mismatched, or repeated access fails closed; unsuccessful paths close
the underlying trace descriptors.

Final focused evidence:

```text
prompt RED: AttributeError: provider has no P7_SOLVE_PROMPT_SHA256
receipt RED: CapabilityExecutionError: Prime solver receipt accessor is unavailable

uv run python -W error::ResourceWarning -m unittest -v \
  tests.test_prime_arc_agi_3_solver_package tests.test_prime_p7_native_provider \
  tests.test_asterion_prime_session tests.test_asterion_prime_runtime \
  tests.test_asterion_prime_architecture
Ran 48 tests in 0.095s
OK

uv run ruff check <final focused source/tests>
All checks passed!

uv run python -m py_compile <final focused source/tests>
exit 0

uv run pyright <final focused source/tests>
0 errors, 0 warnings, 0 informations

git diff --check -- <final focused source/tests>
exit 0
```

The composed E2E test constructs the selected runtime before using a fake
completed native runtime to transition the same injected broker and retrieve a
real adapter-generated package result. Provider listing and construction still
start neither the external worker nor the Pi/model process.
