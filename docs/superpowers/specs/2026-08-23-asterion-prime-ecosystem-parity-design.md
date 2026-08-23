# Asterion Prime Ecosystem Parity Design

## Goal

Close the ten mandatory Prime 0.7.1 `ecosystem.capabilities` scenarios through
an Asterion-owned sealed resource portfolio, exact selected-provider
translation, real pinned-Prime execution, and provider-free evidence. Preserve
the native parity column as Missing and do not imply later interface or
operations parity.

## Closed Scope

The domain is exactly:

1. `ecosystem.context-files`
2. `ecosystem.prompt-templates`
3. `ecosystem.skills`
4. `ecosystem.extensions-lifecycle`
5. `ecosystem.tools`
6. `ecosystem.extension-state-commands`
7. `ecosystem.packages`
8. `ecosystem.mcp`
9. `ecosystem.custom-providers-models`
10. `ecosystem.collision-diagnostics`

All ten scenarios are provider-free. Model/provider registration is verified by
exact identity resolution without sending a model request. MCP credential
refresh is exercised against an owned local fixture through an injected host
service. Package behavior is limited to exact local or installed-distribution
sources. No scenario reads a model credential, performs a provider operation,
or requires a bounded-model authorization.

This design does not add registries, version ranges, source scanning, remote
package installation, arbitrary MCP endpoints, user-interface behavior,
settings parity, or Asterion-native kernel parity.

## Selected Approach

Use a host-owned sealed portfolio. Python validates exact resource identities,
source declarations, scope, digests, and collision freedom before the selected
provider is created. The Prime adapter projects that admitted portfolio into a
private closed frame. The Gateway validates the frame again, calls a
digest-locked module from the pinned Prime build, and returns only safe
identities, counts, digests, lifecycle states, and fixed reason codes.

The rejected alternatives are:

- Point Prime at an operator directory and accept native discovery. This would
  make filesystem contents and Prime precedence an undeclared composer.
- Build a separate bridge for each of the ten features. This would duplicate
  portfolio resolution, collision handling, lifecycle, and evidence logic.

## Authority and Dependency Direction

The flow is:

```text
CLI/host
  -> exact package/source resolution
  -> sealed ecosystem portfolio and collision gate
  -> selected Prime provider
  -> private Gateway ecosystem frame
  -> pinned Prime ecosystem module
  -> body-free result and parity evidence
```

Python remains the only composer. The Gateway does not select resources,
resolve versions, infer scopes, authorize package installation, refresh
credentials, choose models, or activate colliding entries. Prime remains an
exact implementation behind the selected provider; it is not a second catalog
or runner.

Runners continue to receive resolved plans and injected services. They do not
discover resources or start MCP/package services. Operator-owned services are
preflighted and injected before provider construction.

## Provider-Neutral Portfolio

Add a focused provider-neutral module under `src/asterion/control/` with frozen,
body-free values:

- `EcosystemResourceRef`: exact `resource_id`, `version`, `kind`, `scope`,
  `source_id`, and `content_sha256`.
- `EcosystemSourceRef`: an exact approved local-child or installed-distribution
  identity and digest; it contains no locator or path.
- `EcosystemRegistrationRef`: an exact command, tool, or provider/model identity
  that one admitted extension is expected to register.
- `EcosystemPortfolio`: sorted unique resources and expected registrations plus
  an exact portfolio digest.
- `EcosystemCollision`: resource kind, logical identity, and sorted conflicting
  source identities; it never contains paths or resource bodies.
- `EcosystemActivationReceipt`: portfolio digest, feature IDs, lifecycle counts,
  terminal status, safe MCP/package counts, and zero provider/model usage.
- `EcosystemPrivateSourceStore`: an injected host protocol that resolves one
  already-admitted source identity to an exact private root and direct child.

Resource kinds are closed to context file, prompt template, markdown skill,
Python skill, extension, package, and MCP server. Extension commands, tools, and
custom provider/model identities are expected registrations rather than
independently loadable executable resources.

The portfolio builder consumes explicit declarations. It may reuse existing
capability-package source locks and installed-distribution adapters, but it must
not recursively scan their roots. Local resources are exact named children of
an approved canonical root, opened without following symlinks and validated by
identity, type, size, and SHA-256 digest.

## Collision Semantics

There is no precedence. A duplicate logical identity across resources,
extension commands, tools, or provider/model registrations rejects the entire
portfolio before Prime execution. Input ordering cannot select a winner.

The public diagnostic contains only:

- the closed resource/registration kind;
- the stable logical identity;
- sorted source IDs;
- the fixed reason code `ecosystem-resource-collision`.

Prime native winner/loser paths are private observations only. They may confirm
that the real pinned implementation detected the same collision, but they are
never rendered or used as authority.

## Private Materialization Boundary

After host preflight, an injected materializer creates a fresh mode-0700 root
under the control-plane private root. Each admitted resource is copied from an
already held, no-follow source descriptor into a deterministic direct-child
layout. Files are mode 0600, directories are mode 0700, and publication is
atomic. Symlinks, special files, path escapes, duplicate names, replacement
races, digest drift, and partial publication fail closed.

The materialized tree contains only the admitted portfolio and generated
provider-private configuration. It is not a catalog and is never published.
Cleanup runs after teardown and on every failure path. Public values retain only
the portfolio digest and counts.

## Prime Gateway Projection

Add a closed private `asterion.prime-ecosystem-frame/v1` shape containing:

- portfolio and authority digests;
- exact resource identities and private materialized references;
- expected Prime source/artifact/module locks;
- enabled feature IDs;
- MCP host-service socket identity and an opaque credential lease ID;
- fixed byte, entry, process, and deadline limits.

The Gateway checks exact keys, canonical ordering, unique identities, safe
integers, path ownership, file modes, digests, source locks, and feature/resource
consistency before importing the Prime module. It binds the admitted frame
digest before lifecycle effects.

The pinned module uses Prime's real resource, extension, package, MCP, and model
registry APIs against only the sealed tree. Defaults and bundled discovery are
disabled. The module emits a private detailed observation and a public-safe
receipt. It never sends a prompt or invokes a registered custom provider.

## Feature Behavior

### Resource package

- Asterion never discovers context by walking operator workspace ancestors. It
  materializes declared global/project files into the sealed tree, invokes
  Prime's native ordering there, and rejects any undeclared observation.
- Prompt templates parse frontmatter and expand arguments using Prime behavior;
  prompt bodies remain private.
- Markdown and Python skills retain exact identities. Python metadata is
  validated but no arbitrary skill code is imported during metadata discovery.
- Collisions reject atomically with deterministic body-free diagnostics.

### Extension runtime package

- One exact fixture extension registers lifecycle hooks, a command, a tool, and
  a custom provider/model identity.
- Start, session event, shutdown, and teardown occur once in fixed order.
- Extension command state is appended to the session-scoped durable record and
  survives close/reopen without leaking the state body.
- Tool and provider/model registration are resolved by exact identity. The tool
  is invoked only against a deterministic local input; the provider is never
  called.

### Package package

- Reuse Asterion exact package references and source locks.
- Metadata discovery remains provider-free and does not import the package
  implementation.
- Only the exactly selected local-directory or installed-distribution candidate
  may materialize resources. Ambiguity, digest mismatch, ranges, registries,
  remote installation, and source fallback are rejected.

### MCP package

- The portfolio declares one exact local MCP fixture and its closed capability
  set.
- The host owns process launch, deadline, cancellation, and credential refresh.
  The Gateway receives an injected private channel, not executable paths or
  credentials in a manifest.
- Refresh occurs exactly once when the fixture returns the declared auth
  challenge. The refreshed secret is used only on the private channel and is
  absent from events, receipts, errors, logs, and evidence.
- Teardown reaps the owned fixture and reports zero remaining processes.

## Recovery and Failure Handling

Portfolio admission and materialization complete before Prime lifecycle start.
The Gateway durably binds the effect identity before invoking the pinned module.

- Failure before bind performs no Prime effect.
- Failure after bind but before terminal observation is `uncertain`; the same
  effect is never replayed automatically.
- A committed terminal receipt may be projected after restart without reopening
  resource bodies or refreshing credentials again.
- Extension teardown and MCP shutdown are idempotent, bounded, and always
  attempted in reverse start order.
- Any identity, digest, source-lock, mode, lifecycle, count, or cleanup drift
  rejects evidence promotion.

All public exceptions use fixed messages without chained private exceptions.

## Evidence Strategy

Use four real-Prime provider-free evidence packages:

1. `test.prime-ecosystem-resources.provider-free` covers context files, prompt
   templates, skills, and collision diagnostics.
2. `test.prime-ecosystem-extensions.provider-free` covers extension lifecycle,
   tools, extension state/commands, and custom provider/model registration.
3. `test.prime-ecosystem-packages.provider-free` covers exact package source
   selection and materialization.
4. `test.prime-ecosystem-mcp.provider-free` covers local MCP configuration,
   one credential refresh, cancellation, and teardown.

Each command must use the pinned real Prime build, perform zero provider
operations, read zero model credentials, leave zero owned processes, run twice
with identical public digests where the scenario is deterministic, and emit no
private sentinel. Fake adapters remain diagnostic-only and receive no evidence
ID.

The final domain reducer must report 10 selected, 10 passed, zero blocking, zero
provider operations, and PASS for `asterion.prime-gateway`. Every
`asterion.native` result remains Missing.

## Test Matrix

Python `unittest` covers value closure, immutability, exact source selection,
no-follow file handling, collision determinism, materialization rollback,
host-service preflight, recovery, evidence binding, and redaction.

Node `node:test` covers the private frame, pinned module lock, real Prime
resource parsing, lifecycle order, command state reopen, tool/provider/model
registration, package selection, MCP refresh, cancellation, teardown, and
private sentinel exclusion.

Cross-boundary tests cover malformed frames, source/artifact drift, unordered or
duplicate arrays, missing host services, hostile filesystem types, replacement
races, credential refresh failure, lifecycle uncertainty, cleanup failure, and
attempted provider invocation.

Closure requires the four named gates, the exact domain reducer, `make check`,
`make promotion-check`, and `git diff --check`.

## Compatibility and Cost

No public v1 protocol changes are required. Provider-neutral values and narrow
host-service protocols are internal Python APIs; the Gateway frame is private
and versioned. Existing capability/package protocols remain closed and are
reused rather than widened.

All ecosystem implementation and evidence work in this design is provider-free.
Any later request to call a real custom model/provider is a new hypothesis with
separate finite authorization and cannot reuse the completed continual-harness
receipt.
