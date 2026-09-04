# Prime P1 Task 1 report

## Delivered closure

- Added the exact built-in `prime-agent@1.0.0` portable capability package.
- The package declares only `prime.ipython-coding@1.0.0` and binds exactly one executable implementation.
- Added `prime.agent` to the standard runtime factory registry.  Its manifest advertises only `prime.tool.ipython`.
- Updated the existing Prime application assembly/provider to select that exact package, capability, and runtime.
- The frame-only runtime validates a requested capability tuple before yielding any frames.  Any tool other than the exact singleton `prime.tool.ipython` is rejected.

## Rejection coverage

`tests/test_prime_package_runtime_closure.py` proves standard resolution yields only the expected package, capability, runtime, tool capability, and one binding.  It also proves rejection before execution for:

- an alternate runtime tool capability;
- an ambiguous duplicate implementation binding;
- an assembly runtime not declared by the provider; and
- a direct runtime request for `prime.tool.shell`.

## Verification

Passed:

```text
uv run python -m unittest -v tests.test_prime_package_runtime_closure tests.test_builtin_capability_source tests.test_installed_application_provider tests.test_prime_application_provider
# 31 tests, OK

uv run ruff check src/asterion/capabilities/builtin.py src/asterion/capabilities/prime_agent src/asterion/runtimes/prime_agent.py src/asterion/runtime/defaults.py src/asterion/applications/prime_agent/provider.py tests/test_builtin_capability_source.py tests/test_prime_package_runtime_closure.py
# All checks passed

uv run pyright src/asterion/capabilities/prime_agent src/asterion/runtimes/prime_agent.py tests/test_prime_package_runtime_closure.py
# 0 errors
```

The broader requested Pyright invocation including `src/asterion/runtime/defaults.py` has one pre-existing error at line 466: an `object` passed to `float`.  The Prime-specific Pyright target is clean.

## Intentional remaining boundary

This task deliberately does not add model-service resolution, Docker/network execution, a worker, or the `verify --level basic` flow.  The `prime.agent` adapter therefore emits a safe terminal `runtime-unavailable` frame after accepting only the declared tool.  Later P1 tasks replace that inert transport with the bounded model/worker path without widening its public manifest.
