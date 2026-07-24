# Asterion Application Runner

## Boundary

The Python runner executes one already resolved `AssemblyPlan` through an explicitly supplied `AgentRuntimeClient`. The caller supplies application input, run identity, optional `CancellationSignal`, and explicit host services. Asterion does not discover packages or services at execution time.

The plan records runtime-owned and host-owned capabilities separately. The runner verifies the runtime identity and required capabilities, then checks every required host service before invoking the runtime. Supplying a service object satisfies presence only; it does not authorize commands, grant policy, or make the service a sandbox.

## Result and failure semantics

The runner creates one portable `RunRequest`, consumes a complete Agent Runtime Protocol stream, validates lifecycle ordering and run identity, and returns immutable normalized events and artifacts. Provider-native messages and service objects are never returned.

Runtime mismatch, capability mismatch, missing services, invalid input, pre-run cancellation, runtime exceptions, and malformed or incomplete streams fail closed with content-free `ApplicationRunError` messages. During execution, the runner passes the same read-only cancellation signal to the runtime and accepts only its normalized terminal lifecycle.

## Ownership and non-goals

Python Asterion owns this runner. TypeScript retains protocol types and validation but does not implement a second runner. Rust services remain caller-owned and are never started by the runner.

This boundary is not a scheduler, workflow interpreter, service registry, retry engine, package loader, provider selector, persistence layer, process manager, API server, or control plane.

## Minimal use

```python
result = await run_application(
    plan,
    runtime=runtime_client,
    run_id="dci-run-1",
    input_text="Investigate the local corpus",
    host_services={},
)
```

The caller must resolve and authorize everything before this call. A controlled-code plan must provide an already-authorized `executor.controlled` implementation; the runner will neither create nor launch it.
