# Asterion documentation

This hub describes the promoted standalone repository. Start with commands;
read architecture documents when extending the framework.

## Use and verify DCI

- [Capability usage guide](guides/asterion-capability-usage.md) — installation,
  discovery, four verification levels, configuration, costs, and outputs.
- [Complete Asterion DCI reference](guides/asterion-dci-complete-reference.md) —
  research, resume, context management, Judge, benchmark, analysis, export, and
  paper reproduction boundaries.
- [Functional verification guide](verification/asterion-dci-validation-guide.md)
  — provider-free closure, external prerequisites, bounded verification, and
  troubleshooting.

## Understand and extend Asterion

- [DCI capability architecture and gap audit](architecture/dci-capability-audit.md)
  — paper/README claim mapping, installed reachability, protocol
  counterexamples, experiment provenance, and the prioritized delivery route.
- [Agent application framework](architecture/agent-framework.md) — the layer
  model, public boundaries, delivery strategy, and non-goals.
- [Agent Control Protocol](architecture/AGENT-CONTROL-PROTOCOL.md) — optional
  long-running systems, provider interchangeability, authority, journal,
  recovery and safe evidence boundaries.
- [Prime parity ledger](status/PRIME-PARITY-LEDGER.md) — pinned baseline,
  evidence levels, stable domains and explicit Prime/native gaps.
- [Prime Gateway operator guide](guides/prime-control-operator-guide.md) —
  managed-loop setup, provider-free/preflight/bounded gates, authority, costs,
  risks, and the native-kernel boundary.
- [Framework and capability integration](architecture/asterion-framework-capability-integration.md)
  — runtime, adapter, package, capability, assembly, application, provider,
  host service, and CLI integration.
- [Application runner](architecture/application-runner.md),
  [capability execution](architecture/capability-execution.md), and
  [composable packages](architecture/composable-packages.md) — detailed
  execution and composition contracts.
- [Controlled executor operations](operator/rust-executor.md) — Rust sidecar
  policy and process boundaries.
- [Security boundaries](security.md) — extension trust, source selection,
  execution authority, private operator inputs, and redaction.

## Implementation plans

- [Protocol and composition hardening](superpowers/plans/2026-07-24-asterion-protocol-composition-hardening.md)
- [Application authority and executable closure](superpowers/plans/2026-07-24-asterion-application-authority.md)
- [DCI provenance and reproduction](superpowers/plans/2026-07-24-dci-provenance-reproduction.md)

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

Benchmark docs distinguish package-owned suite identities from operator-owned
resources and authority. `asterion-dci benchmark plan` is provider-free;
benchmark execution and paper-score reproduction require separate explicit
authorization.

The historical `538/538` selector result is **mixed-repository only** integration
evidence. Standalone installed acceptance is package-owned and provider-free;
it does not claim that parent-repository comparison as a live result.
