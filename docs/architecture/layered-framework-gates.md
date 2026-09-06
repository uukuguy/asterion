# Layered framework gates

Status: implemented and verified for W5

## Purpose

Framework development needs one provider-free command whose failures identify
the affected boundary without running the full product and promotion suite.
The existing `make check` and `make promotion-check` remain the full regression
and packaging gates. They are intentionally outside the development gate.

## Gate graph

```text
test.framework-provider-free
├── test.framework-core
├── test.cross-language-contracts
├── test.extension-wheels
└── test.provider-integration

bounded end-to-end commands (explicit only)
├── asterion-verify-basic / asterion-verify-complete
├── dci-basic / dci-complete
└── prime-verify-bounded / prime-p1-run ... prime-p7-run

operator-authorized execution
├── asterion-run / dci-run
└── dci-benchmark

full regression (separate)
├── check
└── promotion-check
```

## Boundaries

### Core

`test.framework-core` proves that the dependency-free wheel imports without
product extras and that framework modules do not acquire product dependencies.
It runs `tests.test_core_only_install` directly. The older `test.core-only`
target retains its broader product and documentation boundary checks for
compatibility.

### Cross-language contracts

`test.cross-language-contracts` runs `tests.test_runtime_protocol`,
`tests.test_capability_catalog`, `tests.test_capability_package_protocol`, and
`tests.test_protocol_canonical_ordering`, plus the generic TypeScript
`asterion-runtime` suite. Together these cover the four closed v1 contracts and
additional generic contract behavior. The gate excludes DCI, Prime Gateway,
and the Rust controlled executor. The executor has its own implementation
contract and remains in full regression.

### Extension wheels

`test.extension-wheels` aggregates the three isolated installed-wheel proofs:
public extension, cross-package composition, and cross-runtime semantics. These
tests use deterministic local fixtures and do not load product source.

### Provider integration

`test.provider-integration` runs exact `dci-agent-lite` acceptance. Acceptance
loads metadata and entry points without invoking a model or executing an
application. The provider name is fixed so this gate cannot change meaning
through `ASTERION_PROVIDER`.

### Bounded end to end

Bounded preset execution remains a set of commands with fixed, finite controls.
General `run` and benchmark commands remain operator-authorized execution and
are not described as bounded merely because they have explicit entry points.
No aggregate provider-free target depends on either group. Their existing
authorization, environment, Docker, external source, data, and cost boundaries
remain in force.

## Compatibility

All existing command names retain their behavior. `test-typescript`,
`check-rust`, `check`, and `promotion-check` remain available for full
repository or release validation. W5 only adds aliases and one provider-free
aggregate; it changes no runtime, provider, manifest, or wire contract.

## Acceptance

W5 is complete when:

1. `make test.framework-provider-free` passes without provider credentials,
   model calls, Docker, or an external Prime checkout.
2. `make help` clearly separates the four provider-free layers, explicit
   bounded execution, and full regression.
3. Existing individual W2/W3 and Prime P1-P7 command names remain present.
