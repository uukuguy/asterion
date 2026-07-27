# Asterion Capability Package Protocol and Source Forms Design

> Approved direction: Asterion owns source-neutral capability protocols,
> discovery, composition, execution, and benchmark orchestration. Built-in and
> third-party packages are different source forms of the same portable
> capability package. DCI is the first conformance example: it must be viable
> as an external extension and as an equivalent built-in form.

## Status and supersession

This design supersedes the placement and entry-point decisions in
`2026-07-26-dci-benchmark-orchestrator-design.md`. The earlier behavioral
requirements remain valid: bounded plan-only defaults, explicit execution,
sequential progress, fail-fast behavior, private evidence, compatible resume,
no automatic downloads, and no monetary input requirement.

There is no compatibility obligation for the current `dci.*` protocol names.
Asterion is a new project. The migration is a hard protocol correction, not a
dual-stack compatibility period.

## Problem

The repository currently has generic runtime, package, assembly, catalog,
composition, and execution contracts named as DCI protocols:

- `dci.agent-runtime/v1`;
- `dci.package/v1`;
- `dci.assembly/v1`.

These contracts are already used by non-DCI capability packages such as
controlled code. Their behavior is generic Asterion behavior, but their names
and some ownership boundaries imply that DCI owns them.

The DCI benchmark implementation has the inverse problem. Generic suite
planning, sequential execution, cancellation, progress, evidence security, and
resume behavior currently live in DCI-specific repository-level tools, while
DCI task definitions and launchers appear in global `tools/` and `scripts/`
surfaces. Generic behavior and DCI-specific artifacts are therefore mixed.

Asterion also lacks a first-class contract for a capability package as a
portable unit. It validates individual capability manifests and application
assemblies, but does not yet model:

- the exact closure of one capability package;
- multiple package source forms;
- third-party package discovery and loading;
- source selection without hidden precedence;
- content-equivalent conversion between forms;
- generic benchmark suites supplied by capability packages.

## Goals

- Define Asterion-owned runtime, capability, capability-package, application
  assembly, benchmark-suite, source-declaration, and source-lock protocols.
- Separate portable package identity from source and installation identity.
- Treat built-in packages as one source form, not a privileged package type.
- Support built-in, installed Python distribution, and explicit local
  directory forms first, with archive and registry forms supported by the
  architecture and added in later phases.
- Make package discovery metadata-only until an exact package is selected.
- Resolve exact identities deterministically and fail closed on ambiguity.
- Keep executable bindings in provider factories, never in portable manifests.
- Provide a public SDK and conformance kit that built-in and third-party
  packages use identically.
- Put generic benchmark planning and execution in Asterion.
- Put DCI task catalogs, profiles, dataset contracts, metrics, provenance,
  resources, and implementation bindings in the DCI capability package.
- Prove source-form equivalence by building DCI first as a valid external
  extension and then materializing the same payload as a built-in package.

## Non-goals

- No semantic-version ranges, dependency solver, registry precedence, or
  automatic latest-version selection.
- No runtime source scanning, parent-directory scanning, or implicit
  `sys.path` mutation.
- No claim that installed third-party Python code is sandboxed.
- No commands, executable paths, prompts, credentials, provider configuration,
  environment values, private host paths, or mutable state in portable
  manifests.
- No remote registry implementation in the first delivery phase.
- No provider-backed benchmark run as part of the migration.
- No preservation of the obsolete `dci.*` generic protocol identifiers.

## Core principles

```text
Capability identity != source identity
Capability package != installation method
Built-in != privileged
Form conversion != version upgrade
Application assembly != source selection
Trust decision != capability semantics
Manifest compatibility != execution authority
```

A capability package is an identity-bearing portable payload. A source form is
a way to discover, materialize, and load that payload. An operator source lock
chooses a source. An application assembly chooses exact capability packages and
capabilities, not locations.

## Architecture

```text
CapabilityPackageSource adapters
    -> metadata-only candidates
    -> canonical protocol validation
    -> exact source-lock resolution
    -> portable payload closure and digest validation
    -> selected provider factory load
    -> exact implementation binding validation
    -> InstalledCapabilityPackage
    -> application assembly resolution
    -> deterministic composition
    -> resolved plan
    -> runner / benchmark suite runner
    -> injected runtime and host services
```

Only the selected provider factory is imported. Listing and metadata
description do not load implementation modules.

## Protocol family

### `asterion.agent-runtime/v1`

This replaces `dci.agent-runtime/v1` without a compatibility alias. It remains
the closed cross-runtime request, event-stream, and runtime-manifest contract.
The canonical JSON Schemas, Python validators and values, TypeScript types and
validators, and shared valid/invalid fixtures must change together.

### `asterion.capability/v1`

This replaces `dci.package/v1`. It describes one composable capability,
declarative policy, or executable stage.

The current semantic fields remain where valid, with names changed from
package-oriented to capability-oriented:

- exact `capability_id` and version;
- kind;
- provided and required capabilities;
- required policies;
- consumed and emitted events;
- consumed and produced artifact media types.

Arrays are canonical, sorted, and unique. Executable kinds require exactly one
implementation binding after resolution. Policies remain declarative.

The manifest does not identify a Python class, module, executable, prompt,
command, resource root, provider, or environment.

### `asterion.capability-package/v1`

This new protocol describes one portable capability package closure.

Required concepts are:

- exact `package_id` and version;
- exact sorted member capability refs;
- exact sorted benchmark-suite refs;
- declared public resource identities and media types;
- content digests for identity-bearing resources and implementation artifacts;
- minimum compatible Asterion protocol versions;
- public conformance profile.

The descriptor must enumerate the exact portable payload closure. Extra
identity-bearing members and missing declared members both fail validation.
The package payload digest is computed over a canonical relative-file map; it
does not include the source-form envelope, install location, timestamps,
archive container metadata, wheel `RECORD`, or private operator configuration.

The descriptor cannot grant execution authority. Provider factories and host
preflight supply implementations and services after selection.

### `asterion.application-assembly/v1`

This replaces `dci.assembly/v1`. An assembly declares:

- exact application ID and version;
- exact runtime ID;
- exact capability-package refs;
- exact capability refs used by the application;
- host capability, policy, event, and artifact edges.

The assembly contains no source IDs or paths. Package source selection belongs
to the operator/host layer.

Composition is deterministic and fails closed on missing packages, missing
capabilities, ambiguity, incomplete edges, or cycles.

### `asterion.benchmark-suite/v1`

This new generic protocol describes a suite supplied by a capability package.
It declares:

- exact suite ID and version;
- exact owning capability-package ref;
- an exact sorted task list;
- each task's stable task ID, exact capability ref, and logical binding ID;
- public metric/result contract IDs;
- allowed artifact media types;
- bounded default case limit and concurrency;
- public task notes that contain no inputs, outputs, paths, or provider data.

It contains no dataset path, corpus path, command, launcher, environment value,
prompt, credential, or executable binding.

The selected package provider supplies exactly one `BenchmarkTaskBinding` for
each executable task binding ID. The binding produces immutable task
invocations for the generic runner. Unknown, missing, and duplicate bindings
fail before resource or provider work.

### `asterion.capability-source/v1`

This is an operator-owned source declaration, not part of the portable package
payload. It records:

- source ID;
- source kind;
- expected exact package ref;
- expected payload digest when known;
- private locator and provider-factory configuration.

Locators and factory configuration may contain host paths or distribution
coordinates, so public projections must expose only an opaque source ID, kind,
package ref, and safe digest.

### `asterion.capability-lock/v1`

This operator-owned lock maps an exact package ref and payload digest to one
source ID. It is the only mechanism that resolves multiple available forms.

There is no built-in priority, local override, installed-package priority, or
latest-version fallback. Multiple candidates without an exact lock are
ambiguous even if they claim the same package ref and payload digest.

## Portable capability payload

Every form exposes the same logical payload:

```text
payload/
  capability-package.json
  capabilities/
    <direct canonical JSON children>
  benchmark-suites/
    <direct canonical JSON children>
  resources/
    <declared identity-bearing resources>
  implementations/
    <declared implementation artifacts>
  conformance/
    <portable public test vectors>
```

Catalogs use explicit roots and direct JSON children only. They do not recurse,
scan source trees, follow symlinks, consult registries, or infer precedence.

Implementation artifacts are included in the canonical content map so their
identity survives form conversion. Loading details are held by the source-form
provider envelope, not by portable manifests. Provider output must report
implementation identities that match the canonical payload declarations.

## Source forms

### Built-in

Built-in packages are materialized below `src/asterion/capabilities/` and
shipped in the Asterion distribution. An explicit built-in source table maps
exact package refs to resource roots and provider factories.

Built-in packages pass the same schema, closure, digest, binding, and
conformance checks as every other form. They do not import private runner or
composer state and do not bypass host preflight.

### Installed Python distribution

Production Python extensions register metadata through:

```toml
[project.entry-points."asterion.capability_packages"]
"vendor.package@1.0.0" = "vendor_package.provider:create_package"
```

The distribution also carries the canonical payload below a standardized data
root generated by `asterion capability pack`. The entry-point name identifies
the exact package ref; distribution file metadata identifies the payload data
root without importing the entry-point target. Discovery can therefore read
and validate `capability-package.json` and its declared closure through
`importlib.metadata` while implementation modules remain unloaded.

Only an exact selected candidate's factory is loaded. Entry-point name,
distribution metadata, portable descriptor, provider result, and
implementation identities must agree.

Editable installations use the same form and rules.

### Explicit local directory

Local development uses an operator source declaration containing an explicit
canonical root and explicit provider-factory locator. Asterion does not scan
parents, discover neighboring repositories, or mutate global `sys.path`.

The root and every identity-bearing child must be non-symlinked, remain below
the canonical root, have an exact declared type, and satisfy the same payload
closure and digest checks.

Private local paths never enter public errors, summaries, or evidence.

### Archive

The second delivery phase adds a canonical archive form. Archives require an
exact package ref and payload digest before materialization. Extraction uses a
new private content-addressed directory and rejects absolute paths, `..`,
symlinks, hard-link escapes, duplicate entries, special files, and
case-colliding names.

The materialized payload is validated again independently of the archive
container.

### Registry or remote object

The third delivery phase adds remote acquisition. Remote references require an
exact package ref, payload digest, source identity, and verified publisher
signature. Downloads materialize into a private content-addressed cache.
Registry metadata never grants execution authority and does not introduce
version ranges or automatic upgrades.

## Source adapter interface

Asterion defines one public `CapabilityPackageSource` interface with four
separate phases:

1. `discover_metadata()` returns body-free candidates without importing
   implementation code.
2. `open_payload()` returns a bounded resource view for an exact selected
   candidate.
3. `validate_source_identity()` binds source metadata to the portable payload.
4. `load_provider()` loads only the selected implementation provider.

Every adapter returns the same immutable candidate and installed-package value
types. Source-specific objects cannot reach composer or runner internals.

## Public third-party SDK

Third-party and built-in implementations depend only on a versioned public SDK,
not on private Asterion modules. The SDK exposes:

- capability package provider and installed-package values;
- capability refs and benchmark-suite refs;
- package invocation and execution-result values;
- runtime, cancellation, and read-only host-service protocols;
- artifact projection helpers;
- conformance and identity helpers.

Built-in conformance rejects imports from private Asterion implementation
modules. If a built-in package cannot be exported and run against the public
SDK, its boundary is invalid.

Author tooling is:

```text
asterion capability init
asterion capability validate
asterion capability inspect
asterion capability test
asterion capability pack
asterion capability convert
```

The project publishes JSON Schemas, a minimal declarative example, a complete
implemented example, a provider template, and a reusable conformance test kit.

## Form conversion

Built-in is one target form, not an upgrade tier. Conversion changes only the
source envelope:

```text
source form
    -> validated canonical payload
    -> target form envelope
    -> target materialization
```

The conversion command accepts exact source and target forms:

```bash
asterion capability convert \
  --package dci@1.0.0 \
  --from python-distribution \
  --to builtin
```

The reverse is equally valid:

```bash
asterion capability convert \
  --package dci@1.0.0 \
  --from builtin \
  --to archive
```

Conversion succeeds only when package, capability, suite, implementation,
resource, and full payload identities are unchanged after target
materialization. If any identity-bearing content changes, the operation is a
new package build and requires a new version; it is not conversion.

The source lock must explicitly select the target form after conversion.
Temporary coexistence never triggers implicit built-in preference.

## Generic benchmark orchestration

Asterion owns a domain-neutral benchmark subsystem. It receives:

- a validated suite manifest;
- exact immutable task bindings;
- a resolved application plan;
- the selected runtime;
- injected host services;
- an operator execution gate and cancellation signal.

It does not discover packages, select providers, authorize commands, download
data, choose runtimes, start services, or interpret DCI profiles.

It provides:

- metadata-only plan mode by default;
- explicit execute mode;
- deterministic task order;
- bounded per-task limits and concurrency;
- sequential execution and stop-on-failure;
- compatible resume;
- process-tree cancellation and bounded cleanup;
- private descriptor-bound evidence;
- body-free public progress and summary;
- one terminal suite result.

The generic subsystem lives in framework-owned modules and imports no built-in
capability package.

## DCI as the first form-equivalence package

DCI is designed first as if it were an external extension:

```text
dci capability payload
  capability-package.json
  capabilities/
    research
    evaluation
    benchmark
    analysis
    export
  benchmark-suites/
    github
    paper-main
    all
  resources/
  implementations/
  conformance/
```

The DCI package owns:

- DCI capability and policy manifests;
- the 15 stable benchmark task variants;
- dataset, corpus, profile, metric, and result contract identities;
- exact DCI task bindings;
- DCI-specific provenance and public projections;
- DCI implementation resources.

It does not own:

- generic package discovery or composition;
- generic suite scheduling;
- generic cancellation, logging, evidence, or resume;
- root-level tools or launchers;
- provider selection or runtime construction.

The external Python-distribution form must install into a clean Asterion
environment and pass conformance using only the public SDK. The same canonical
payload is then materialized as the built-in form below
`src/asterion/capabilities/dci/`.

The built-in and external forms must produce identical package, capability,
suite, implementation, and resource identities. Source provenance differs;
capability semantics do not.

The current `src/asterion/capabilities/dci_research` directory is renamed to
the complete `dci` package because it already contains research, evaluation,
benchmark, analysis, and export members. DCI-specific benchmark catalogs,
resources, and implementation code move into that package. Repository-level
DCI benchmark tools and launchers are removed.

The top-level `src/asterion/dci` namespace is eliminated by the completed
migration. Its modules are classified rather than mechanically relocated:

- DCI capability implementations, contracts, profiles, datasets, evaluation,
  provenance, and resources move into `src/asterion/capabilities/dci`;
- DCI product selection and CLI translation move into the DCI application
  adapter;
- any genuinely domain-neutral mechanism moves into a framework subsystem only
  after tests prove that it imports and names no DCI concept.

The DCI product CLI becomes an application adapter. It may translate a
DCI-oriented command into a generic host request but cannot contain another
composer, suite runner, or source resolver.

## Failure and security model

All of the following fail before capability execution:

- noncanonical protocol documents;
- unsorted or duplicate arrays;
- missing or extra portable payload members;
- package, entry-point, source, provider, or implementation identity mismatch;
- duplicate exact candidates without an exact source lock;
- version ranges or unknown versions;
- missing, duplicate, or unknown implementation bindings;
- symlink, root escape, special-file, archive traversal, or digest mismatch;
- runtime or host-service incompatibility;
- selected provider import or factory failure;
- remote payload without a pinned digest and verified signature.

Errors are stable and body-free. They do not expose credentials, source
locators, local paths, package contents, provider payloads, prompts, answers,
corpus text, or raw child output.

Installed third-party Python providers are trusted process code after explicit
selection. Asterion validates contracts and controls injected authority, but
does not claim to sandbox imported Python.

## Validation and conformance

Protocol changes update in one commit boundary:

- canonical JSON Schemas;
- Python constants, validators, and immutable values;
- TypeScript constants, types, and validators;
- all valid and invalid fixtures;
- every built-in manifest and assembly;
- documentation examples and schema links.

Required package tests cover:

- canonical success and every invalid fixture;
- exact identity agreement across source, descriptor, provider, and bindings;
- deterministic discovery and composition;
- duplicate-source ambiguity;
- metadata-only listing without provider import;
- immutable inputs and results;
- missing host service and runtime incompatibility;
- redaction sentinels;
- local-root and archive escape attempts;
- conversion identity equivalence in both directions.

Every built-in package must pass:

1. built-in conformance inside the Asterion source and built wheel;
2. externalization conformance after export and installation into a clean
   environment;
3. source-form equivalence against its canonical payload digest.

Promotion checks verify source-tree resources, built-wheel resources, entry
points, schemas, package closures, implementation identities, and application
assemblies. Provider operations and full datasets remain zero.

## Delivery phases

### Phase 1: protocol correction

- Replace the three generic `dci.*` protocols with the Asterion protocol
  family.
- Add capability-package, benchmark-suite, source, and lock schemas and values.
- Update Python, TypeScript, fixtures, built-in manifests, and assemblies.
- No compatibility aliases.

### Phase 2: package and source core

- Add immutable candidate, portable payload, installed-package, source adapter,
  and source-lock models.
- Implement built-in, installed-distribution, and explicit-local-directory
  adapters.
- Add public SDK, author templates, metadata-only discovery, and conformance
  tooling.
- Convert controlled code and a minimal fixture package first.

### Phase 3: generic benchmark subsystem

- Extract domain-neutral planning, execution, progress, cancellation, evidence,
  and resume from the DCI coordinator.
- Add generic benchmark-suite resolution and CLI host surface.
- Preserve the already verified bounded execution and privacy invariants.

### Phase 4: DCI external-first migration

- Assemble the complete DCI portable payload.
- Replace root launchers with DCI logical task bindings.
- Pass external-distribution conformance in a clean environment.
- Materialize the same payload as the built-in form.
- Prove external/built-in identity and behavior equivalence.
- Remove obsolete global DCI benchmark tools and paths.

### Phase 5: offline and remote forms

- Add canonical archive conversion and content-addressed materialization.
- Add registry/remote adapters only after digest, signature, namespace, cache,
  and offline rules pass independent design and security review.

## Acceptance criteria

The design is implemented only when:

- no generic protocol uses a `dci.*` identifier;
- generic framework modules import no DCI package;
- the completed source tree has no top-level `asterion.dci` implementation
  namespace;
- every application references exact capability-package and capability refs;
- built-in and third-party packages use the same installed-package model;
- metadata listing imports no selected or unselected provider;
- ambiguous sources have no implicit precedence;
- DCI has no repository-root benchmark runner or launcher;
- DCI external and built-in forms share one payload digest and exact member
  identities;
- DCI benchmark PLAN remains provider-free and creates no execution output;
- full provider-free repository and promotion gates pass from the built wheel.
