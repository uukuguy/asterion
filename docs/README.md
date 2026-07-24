# Asterion documentation

This hub describes the promoted standalone repository. Start with commands;
read architecture documents when extending the framework.

## Use and verify DCI

- [Capability usage guide](guides/asterion-capability-usage.md) — installation,
  discovery, four verification levels, configuration, costs, and outputs.
- [Complete Asterion DCI reference](guides/asterion-dci-complete-reference.md) —
  research, resume, context management, Judge, benchmark, analysis, export, and
  evidence semantics.
- [Functional verification guide](verification/asterion-dci-validation-guide.md)
  — provider-free closure, external prerequisites, bounded verification, and
  troubleshooting.

## Understand and extend Asterion

- [Agent application framework](architecture/agent-framework.md) — the layer
  model, public boundaries, delivery strategy, and non-goals.
- [Framework and capability integration](architecture/asterion-framework-capability-integration.md)
  — runtime, adapter, package, capability, assembly, application, provider,
  host service, and CLI integration.
- [Application runner](architecture/application-runner.md),
  [capability execution](architecture/capability-execution.md), and
  [composable packages](architecture/composable-packages.md) — detailed
  execution and composition contracts.
- [Controlled executor operations](operator/rust-executor.md) — Rust sidecar
  policy and process boundaries.

## Promote or extract the project

- [Standalone extraction guide](architecture/asterion-standalone-extraction.md)
  — root inventory, external dependencies, promotion gates, rollback, and the
  future DCI plugin decision point.

Run all local documentation checks from this repository root:

```bash
make docs-check
```

## Evidence labels

- **Implemented** — production code and an entry point exist.
- **Verified** — the named command passed within its stated boundary.
- **External-limited** — the boundary is implemented but depends on external
  Pi, data, a service, or credentials.
- **Not rerun** — the implementation exists, but a full dataset or published
  score was not reproduced in the current work.

The historical `538/538` selector result is **mixed-repository only** integration
evidence. Standalone installed acceptance is package-owned and provider-free;
it does not claim that parent-repository comparison as a live result.
