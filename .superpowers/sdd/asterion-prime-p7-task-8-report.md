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
