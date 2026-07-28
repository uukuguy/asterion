# Asterion architecture

## Package source forms

Asterion uses exact source forms, not heuristic selection. Built-in is one
generic source form. The external installed-distribution path is the clean-wheel
proof that the same portable payload can be selected by an exact source lock
without source scanning or registry precedence. If multiple visible candidates
would require implicit precedence, selection is ambiguous and fails closed.
Archive and registry source forms are deferred to a separate security design.

## Generic benchmark dependency direction

The benchmark subsystem follows one closed dependency direction:

```text
CLI host -> package/application resolution -> benchmark plan
         -> exact task bindings -> runner -> injected executor/services
```

The CLI host parses exact public identities and selects package-source metadata.
Application and package resolution validate the complete suite and capability
closure before any implementation is loaded. Planning produces an immutable,
bounded plan. Only after the host has received explicit execution authority may
it load the selected package providers and attach one exact implementation
binding to each task.

The runner receives that resolved plan, a cancellation signal, an evidence
store, and an executor. It executes tasks sequentially and stops on failure or
cancellation. It does not discover packages or providers, choose a runtime,
authorize work, retry tasks, construct host services, or infer operator
configuration. Process creation is confined to
`asterion.benchmarks.process`, which consumes an already-authorized immutable
process plan.

## Operator configuration ownership

Application packages own translation of operator configuration. Dataset and
corpus locations, executable paths, environment values, credentials, provider
settings, prompts, and application-specific limits stay outside portable
manifests and outside generic benchmark orchestration. A selected application
or task implementation translates operator-owned inputs into an opaque private
invocation or an authorized process plan and injects the required services at
the host boundary.

Generic benchmark code owns suite resolution, bounded planning, deterministic
task ordering, sequential orchestration, cancellation, public progress, and
private evidence mechanics only. Its public plan and result projections use
explicit allowlists; private payloads, paths, process output, host-service
values, and credentials are never serialized. Prior evidence and operator
configuration do not grant execution authority.

The wheel publishes the generic implementation under
`asterion.benchmarks` and includes the canonical
`asterion.benchmark-suite/v1` schema as a package resource. Product-specific
benchmark implementations depend on these public contracts; the generic
subsystem does not depend on product packages.

Security boundaries for manifests, source locks, operator inputs, and deferred
archive or registry forms are documented in [Security boundaries](security.md).
