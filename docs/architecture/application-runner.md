# Asterion Application Runner

## Boundary

The Python runner executes one already resolved `AssemblyPlan` through an explicitly supplied `AgentRuntimeClient`. The caller supplies application input, run identity, optional `CancellationSignal`, and an exact host-service mapping opened by host preflight. Asterion does not discover packages, select runtimes, or discover host services at execution time.

The plan records runtime-owned and host-owned capabilities separately. The application host selects one exact runtime factory binding, opens the selected host services in one async scope, injects them into `RuntimeFactoryContext.host_services`, and only then constructs the runtime. The runner independently rechecks runtime identity, runtime capabilities, and required service presence before package work. The service scope closes after the invocation, including failure or cancellation. Supplying a service object satisfies presence only; it does not authorize commands, grant policy, or make the service a sandbox. Host services remain operator-owned, read-only contracts.

## Result and failure semantics

The runner creates one portable `RunRequest`, consumes a complete Agent Runtime Protocol stream, validates lifecycle ordering and run identity, and returns immutable normalized events and artifacts. Provider-native messages and service objects are never returned.

Runtime IDs and runtime capability arrays are canonical: IDs use the protocol
identifier grammar and capability arrays are sorted and unique. The same applies
to `RunRequest.requested_capabilities` when present and to the capability array
in `run.started`. This is validation, not sorting-on-behalf-of-the-caller. A
complete stream has one run ID, contiguous sequences beginning with
`run.started`, and exactly one terminal event. Every `tool.call` has one unique
later `tool.result` with the same call ID before that terminal event; duplicate
calls/results, a result without a call, or a call still unmatched at the
terminal event are invalid.

Validated TypeScript values and Python runner outputs are deeply immutable
snapshots, so subsequent caller or provider mutation cannot alter the accepted
contract value. The runtime protocol itself does not declare global artifact-ID
cardinality. The stronger cross-package identity rule is owned by the composed
application runner described in the capability-execution boundary.

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
