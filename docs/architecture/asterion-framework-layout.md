# Asterion Framework Layout

## Ownership

**Asterion owns framework contracts.** Its authoritative Python implementation
lives under `src/asterion/`: runtime protocol and hosts, normalized adapters,
package catalogs and composition, static assembly, and host-service contracts.

**Asterion must not import the DCI baseline.** Its first-party DCI capability and
application are modular Asterion namespaces. The mixed-repository dependency
The parent workspace's `src/dci` is a frozen, source-only
comparison baseline with its own framework implementation.

```text
src/asterion/                         sole product distribution
parent workspace src/dci/             mixed-repository, unpackaged benchmark baseline
src/asterion/capabilities/dci_research/  bundled DCI capability and manifests
src/asterion/applications/dci_agent_lite/ bundled provider and assemblies
src/asterion/capabilities/controlled_code/ controlled-code declarative packages
packages/typescript/asterion-runtime/ TypeScript validation and host types
packages/rust/controlled-executor/    explicit controlled-execution service
```

## Stable DCI product entry

The verified mixed-repository source-baseline
`../scripts/examples/dci_basic_example.sh` and
`../scripts/examples/dci_runtime_context_example.sh` continue loading repository
`.env` configuration and invoke `dci.benchmark.pi_rpc_runner` through
`PYTHONPATH=../src`. The baseline is not installed by the Asterion wheel.

The installed product uses exact application identity:

```bash
asterion list --provider dci-agent-lite
asterion run --provider dci-agent-lite \
  --application dci.research-capability@1.0.0 \
  --runtime pi.reference
```

Plain `asterion list` remains metadata-only. Application listing loads only the
explicitly selected provider. `--application` selects the one canonical
assembly whose declared runtime matches `--runtime`; zero or multiple matches
fail before runtime construction. `--assembly PATH` remains an advanced
explicit compatibility path and must itself declare the selected runtime.

## Wire compatibility

Generic framework contracts are Asterion-owned:
`asterion.agent-runtime/v1`, `asterion.capability/v1`,
`asterion.capability-package/v1`, and
`asterion.application-assembly/v1`. The controlled executor remains the
separate `dci.executor/v1` service protocol. The generic contract rename is a
hard boundary: no compatibility aliases accept the retired identities.

## Boundaries

- Asterion never imports `src/dci` and its wheel contains no `dci` package.
- The source baseline never imports Asterion.
- Capability and application roots are declarative; they are not alternate
  Python import roots.
- TypeScript validates canonical contracts but does not duplicate Python
  composition or resolution.
- The Rust service is never started or authorized merely by importing Asterion.
- Registry publication, workflow scheduling, automatic service discovery,
  aliases, version ranges, and implicit latest selection remain out of scope.

## Verification

Run these checks from the standalone repository root:

```bash
make test
make test-typescript
make check-rust
```
