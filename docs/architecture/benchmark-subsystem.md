# Generic benchmark subsystem

The benchmark subsystem is a domain-neutral orchestration layer. It resolves
portable application and capability-package declarations into one immutable,
exact benchmark plan, then executes that plan through implementations and host
services selected outside the runner.

The dependency direction is:

```text
CLI host -> package/application resolution -> benchmark plan
         -> exact task bindings -> runner -> injected executor/services
```

The CLI host owns source selection, source-lock validation, application
selection, authorization, and injection. Resolution reads portable metadata and
payload declarations without importing implementations. Planning fixes the
application, suite, task order, case limit, and package digests before any
execution authority is consumed. After authorization, the host loads only the
selected providers and supplies exact task bindings to the sequential runner.

The runner does not discover packages, choose providers, authorize work, start
services, retry tasks, or create process policy. It accepts a resolved plan,
exact implementations, cancellation, evidence storage, and an already
authorized executor. The process adapter is the only generic benchmark module
that starts subprocesses, and it accepts only payloads issued by its paired
host-owned authority.

Application packages own translation from operator configuration into
application-specific task invocations and injected services. Dataset locations,
corpus locations, credentials, provider settings, executable paths, environment
values, and mutable state therefore remain outside portable manifests and
generic public serialization. Generic benchmark code owns orchestration and
body-free evidence only; it does not interpret product configuration.

The canonical benchmark-suite schema is shipped in the wheel at
`asterion/schemas/benchmark-suite/v1/benchmark-suite.schema.json`, alongside
every module under `asterion.benchmarks`.
