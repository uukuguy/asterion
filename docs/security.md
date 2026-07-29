# Security boundaries

Asterion separates portable metadata, source selection, implementation loading,
and execution authority. Passing one boundary never grants the next.

## Extension trust

Capability discovery is metadata-only and must not import provider modules.
Source resolution requires an exact package identity and, when candidates are
ambiguous, an exact source lock. Matching payload digests do not create
precedence or remove ambiguity.

After exact selection, loading an installed extension executes its provider
code. That code is part of the operator's trusted computing base. Asterion
validates package identity and conformance; it does not sandbox arbitrary Python
extensions.

## Portable and private values

Portable manifests describe compatibility, never authority. They must not
contain prompts, credentials, commands, executable paths, environment values,
provider configuration, mutable state, private dataset or corpus paths, or
evidence locations.

The operator owns credentials, provider configuration, DCI datasets and
corpora, private environment, executor policy, cancellation, and evidence
storage. An optional DCI amount remains private configuration. It is not
required by generic benchmark authorization and never grants execution
authority.

Public output and errors must omit prompts, answers, provider payloads, corpus
text, raw process output, host-service values, credentials, and private paths.
Tests use sentinel secrets to enforce this redaction boundary.

## Execution and future sources

Selecting a package source does not authorize a run. Benchmark execution
requires a fresh, explicit decision from an embedding host plus exact
implementations and operator-owned services. Existing configuration, caches,
plans, evidence, credentials, paths, or amounts never imply consent.

Archive and registry sources are intentionally unsupported. Their provenance,
verification, signature, trust, update, revocation, and failure semantics
require a separate approved security design before implementation.
