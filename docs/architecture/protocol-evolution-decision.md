# Evidence-Led Protocol Evolution Decision

> Status: approved W4 decision. Decision: retain the closed v1 contracts.

## Decision

W2 and W3 do not demonstrate a requirement for a new portable protocol
version. Asterion retains these contracts unchanged:

- `asterion.agent-runtime/v1`
- `asterion.capability/v1`
- `asterion.capability-package/v1`
- `asterion.application-assembly/v1`

No v2 schema, Python validator, TypeScript type, fixture, compatibility mode, or
migration path is introduced. Host-local authority and provider construction
remain host APIs rather than manifest claims.

## Evidence Matrix

| Demonstrated requirement | Existing expression | Boundary |
|---|---|---|
| Exact external package and application identity | Package manifest plus exact package, capability, application, and runtime refs in assembly/provider values | v1 wire and provider |
| Digest-bound portable resources | Package `resources` and `conformance` entries; prepared payload digest | v1 wire and host preparation |
| Metadata-only discovery and selected-only loading | Python distribution entry points and discovery/load separation | Host/provider API |
| One executable implementation per capability | Capability `kind`, exact implementation binding, and runner validation | v1 wire and host binding |
| Cross-package order | Capability event/artifact consumption and capability requirements | v1 wire expression and host composition |
| Package implementation ownership | Prepared payload capability refs bound to a fresh process-local installed-package snapshot | Host authority |
| Install-order-independent composition | Exact sorted refs and deterministic catalog/composer behavior | v1 wire and host composition |
| Provider-owned runtime construction | Exact `runtime_id`, runtime manifest, `RuntimeFactoryBinding`, and immutable factory context | v1 wire and provider API |
| Cross-runtime result equivalence | The same capability manifest and implementation executed by two exact assemblies; capability outputs compared after routing projection | Existing application/provider shape |
| Runtime cancellation | Host `CancellationSignal` and terminal `run.completed` with `status=cancelled` | Existing runtime host API and v1 event |
| Missing host service | Assembly `host_capabilities` and runner preflight against injected services | v1 wire and host runner |
| Runtime mismatch | Assembly/runtime-manifest exact identity comparison | v1 wire and host runner |
| Public result and privacy boundary | Capability event/artifact declarations, immutable results, validation, and public projection | v1 wire and host policy |

The package manifest remains compatibility metadata. It does not gain provider
factories, executable paths, commands, credentials, runtime options, host
services, mutable state, or authority tokens. The assembly continues to list
the exact selected closure. Python wheel dependency metadata helps installation
but does not select or authorize packages at runtime.

## Observed Limitations

An assembly selects one exact `runtime_id`; it cannot declare an interchangeable
runtime set or compatibility relation. W3b did not require such a field. Two
provider-owned exact application routes executed the same installed capability
and the acceptance compared their public semantics. Adding a runtime range or
fallback rule now would weaken exact deterministic selection without satisfying
an unmet case.

Portable package manifests also do not declare distribution dependencies.
W3a expressed its executable graph through capability edges and its exact
selected closure through the application assembly. The Contoso wheel declared
its installation dependency using standard distribution metadata. No registry,
non-Python distribution, or package-only dependency case demonstrated a missing
portable edge.

Application providers and implementation factories are Python host interfaces.
W2 proved an independently installed Python extension. It did not demonstrate
a need for a language-neutral application-provider wire protocol.

These are recorded limitations, not implied commitments to v2.

## Future Version Triggers

A separate protocol version is considered only after a concrete integration
case proves that exact v1 composition cannot express one of these needs:

1. one portable application must advertise multiple interchangeable runtimes
   with deterministic selection semantics that separate assemblies cannot
   express;
2. a non-Python package source needs portable distribution dependency edges
   that capability edges and an exact assembly closure cannot express;
3. a cross-language application provider needs a portable discovery and
   construction contract;
4. cancellation needs portable reason, acknowledgement, or deadline semantics
   beyond the current host signal and terminal status;
5. a real capability graph needs concurrency, cardinality, or named ports that
   the current deterministic edge model cannot represent.

Such a case must define its authority model, compatibility behavior, migration
path, schema, Python and TypeScript parity, and positive and negative fixtures.
It must produce a new version rather than modifying v1 in place.

## Verification Basis

The decision rests on these provider-free installed-wheel commands:

```bash
make test.public-extension
make test.cross-package-extension
make test.cross-runtime-extension
```

They cover independent public extension installation, two-package deterministic
execution and ownership, and one capability through two runtime adapters with
cancellation and preflight rejection. The W2-to-W3 implementation range has no
changes under `schemas/` or the four closed Python protocol validators. W5 will
organize these commands into layered release gates; it does not change this
protocol decision.
