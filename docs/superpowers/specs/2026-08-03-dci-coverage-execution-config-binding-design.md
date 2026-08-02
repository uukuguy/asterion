# DCI Coverage Execution-Config Binding Design

## Goal

Bind every Task 8 coverage plan, authorization, and receipt to one SHA-256 of
the exact effective Agent/runtime execution settings. A prepare/execute drift
must fail before benchmark-host construction or provider loading, while
credential rotation, private paths, raw provider configuration, and environment
values overridden by the host must not change the digest.

## Ownership and dependency direction

The binding remains entirely inside the DCI product:

- `benchmark_host.py` owns the exact real-host runtime override resolution and
  exposes one narrow digest-returning helper for the coverage coordinator.
- `benchmark_executor.py` contributes a product-private digest of the exact
  effective coverage request behavior derived from its existing constants.
- `pathlight_experiment_cli.py` stores and verifies only the resulting SHA-256.

No generic framework module imports DCI. The helper returns only a lowercase
SHA-256 and never returns or serializes the underlying settings.

## Effective settings

The host helper must use the same `resolve_dci_runtime_options()` call and fixed
overrides as `DciBenchmarkHost._default_executor()`. There is one definition of
the fixed host override set and one definition of the executor constructor
settings, reused by both executor creation and digest calculation.

The digest covers the settings that can affect the five coverage tasks:

- fixed runtime, provider, and model;
- effective executor tools (`read,grep`) after its request-level override;
- fixed runtime context level;
- effective timeout, thinking level, and Node old-space memory;
- effective authentication mode, session retention, and extra arguments;
- fixed executor profile and experiment profile;
- each exact task ID with its effective mode, maximum turns, concurrency,
  maximum native attempts, externalized-tool-result behavior, case limit ten,
  and zero-Judge behavior.

The mapping is canonicalized internally and domain-separated before hashing.
Only the digest crosses into the plan.

Environment values for provider, model, runtime, tools, max turns, and context
remain irrelevant when the real host overrides them. Credential values and
irrelevant private environment keys never enter the digest. Effective timeout,
thinking, or Node-memory changes do change it. Changes to the fixed host
overrides or executor task defaults change it when they alter effective coverage
behavior.

## Authority chain

`prepare` loads operator configuration without creating a host or loading a
provider, computes `execution_config_sha256`, and stores that single field in
the private plan. The existing `plan_sha256` therefore binds it.

The separate 0600 authorization must repeat the same
`execution_config_sha256`; authorization validation requires exact equality to
the plan before any execution configuration or host is created.

`execute` loads the current private operator configuration, recomputes the
effective digest, and compares it with the plan before registry preflight and
before host construction. A mismatch returns the existing context-free command
failure. Unchanged effective configuration proceeds normally.

Every receipt repeats `execution_config_sha256`. Receipt publication copies it
from the validated plan, and receipt-chain validation requires exact equality
to the plan so resume cannot cross an execution-config boundary.

## Privacy and failure behavior

The plan, authorization, receipt, status output, and stderr contain no
credentials, private paths, raw environment mapping, or raw provider
configuration. Tests place sentinel credentials and paths in `.env` and assert
they are absent from every plan serialization and public output.

Malformed or mismatched digests fail closed with the existing fixed stderr.
Configuration drift is checked before `_create_host`, so neither a custom test
host nor the real host/provider boundary can be reached.

## Test strategy

TDD first extends the experiment CLI tests to require:

1. an exact SHA-256 field in plan and authorization, with no sentinel leakage;
2. identical digests across credential rotation and changes to overridden
   provider/model/runtime/tools/max-turns/context environment values;
3. rejection before host/provider for effective timeout, thinking, or
   Node-memory drift;
4. rejection before host/provider when a fixed host runtime/context override or
   executor native-attempt/default setting changes;
5. successful unchanged execution with the existing five tasks, ten cases per
   task, 50 Agent operations, zero Judge operations, and 5,000,000-microusd cap;
6. receipt binding and tamper rejection.

Focused unit tests, Pyright, Ruff, and whitespace validation complete the slice.
