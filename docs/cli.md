# Asterion CLI

## Generic benchmark commands

The generic benchmark host resolves exact application, suite, package-source,
and payload identities before executable bindings are loaded:

```text
asterion benchmark plan --application ID@VERSION --suite ID@VERSION
asterion benchmark run --application ID@VERSION --suite ID@VERSION --execute
asterion benchmark resume --application ID@VERSION --suite ID@VERSION --run-id ID --execute
```

All three commands accept `--case-limit N`,
`--capability-source-lock PATH`, and `--evidence-root PATH`. Source locks are
operator-owned `asterion.capability-lock/v1` documents and the option may be
repeated. If `--case-limit` is omitted, the suite's finite
`default_case_limit` is used; a larger or nonpositive limit is rejected.

`plan` is the default-safe operation. It prints the immutable public plan,
does not load capability provider implementations, and does not create
evidence. The printed JSON contains only the run ID, exact application and
suite identities, finite case limit, and ordered public task descriptors.

`run` and `resume` require `--execute` in the current invocation. The flag is
the explicit external execution gate and is checked before metadata discovery
or provider loading. Configuration files, caches, prior evidence, and
operator environment values never grant execution authority. `resume`
additionally requires the exact prior run ID and accepts only compatible
evidence for the same application, suite, source and payload locks, ordered
tasks, and case limit.

After authorization, the host loads only the exact package providers selected
by the rendered plan, resolves their task bindings, injects the task executor
and cancellation signal, and runs tasks sequentially. Evidence is private and
descriptor-bound beneath `--evidence-root`. Failure or cancellation stops
later tasks; cancellation is recorded before the command returns nonzero.

Dataset, corpus, prompt, provider, amount, cost, and `.env`
arguments are intentionally absent. Domain-specific resource selection,
provider credentials, command authorization, and optional `.env` loading
belong to the operator or application host outside `asterion.benchmarks`.
