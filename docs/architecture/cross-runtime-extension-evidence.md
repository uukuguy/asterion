# Cross-Runtime Extension Evidence

> Status: proposed for W3b implementation. Protocol impact: none.

## Purpose

W3b proves that one runtime-neutral executable capability retains the same
public result semantics through two independently owned runtime adapters. The
proof stays provider-free and uses installed extension wheels outside the
repository source tree.

The subject is `acme.research@1.0.0`. W2 already proved that its implementation
depends only on the public application and capability SDKs. W3a removed its
adapter-specific text expectation, so it now accepts any valid
started/text/completed runtime stream with a non-empty text delta and projects
only a fixed `acme.research.completed` event and
`application/vnd.acme.research+json` artifact.

The adapters are:

| Owner | Runtime | Application |
|---|---|---|
| Acme extension | `acme.inline` | `acme.research-application@1.0.0` |
| Contoso extension | `contoso.inline` | `contoso.research-compat@1.0.0` |

This choice keeps DCI, Prime, Native, model providers, Docker, credentials, and
product data outside the framework acceptance boundary. It verifies the public
extension path rather than creating another framework-owned runtime registry.

## Installed Application Shape

The Contoso wheel adds one assembly owned by the existing `contoso-audit`
application provider. The assembly references only `acme.sample@1.0.0` and
`acme.research@1.0.0`, declares `contoso.inline`, and has no host capabilities,
policies, events, artifacts, commands, configuration, or executable paths.
Its exact application-index entry selects the existing Contoso provider.

The provider exposes the existing audited cross-package application and the new
compatibility application in canonical identity order. Its runtime factory
accepts only those exact Contoso application identities, version `1.0.0`, the
`contoso.inline` runtime ID, empty options, and empty host services. Acme keeps
its own provider and runtime factory. Neither extension imports the other
extension's Python implementation.

The two installed CLI results have different application and runtime IDs by
design. After projecting those routing identities, their capability event and
artifact tuples must be byte-equivalent and exactly match the Acme public
result. Runtime text is private adapter output and is validated but not
projected by the capability.

## Cancellation Boundary

Both inline adapters implement the same closed runtime cancellation behavior.
When the supplied signal is already cancelled, or becomes cancelled after the
started event, the adapter emits exactly one `run.started` event followed by
one terminal `run.completed` event with status `cancelled`. It emits no text,
tool call, artifact, provider body, input, or environment value. Normal runs
retain the existing started/text/completed lifecycle.

The focused acceptance constructs both installed runtime clients through their
provider-owned public `RuntimeFactoryBinding` values. It compares their exact
cancelled event streams for the same run ID and validates each with
`parse_event_stream`. The composed runner's pre-cancel check remains the outer
boundary and continues to reject before capability execution.

## Missing-Service and Runtime-Mismatch Boundaries

Missing-service rejection belongs to the shared runner, not to either adapter.
For each resolved installed application plan, the acceptance creates an
immutable test-only plan snapshot requiring `compat.missing-service`, supplies
an empty service map, and calls the same composed runner. Both calls must raise
the fixed body-free `application host service is unavailable` error before the
capability implementation invokes either runtime.

The same suite crosses the resolved plans and runtime clients. Each mismatched
pair must raise the fixed body-free `application runtime identity does not
match` error before capability or runtime work. These test-only plan snapshots
do not alter a portable assembly or claim that manifests grant host authority.

## Acceptance Evidence

`make test.cross-runtime-extension` is the W3b acceptance command. It builds the
core, Acme, and Contoso wheels once, installs them without dependencies in one
clean external virtual environment, and removes repository paths from the
environment. It then:

1. executes the exact Acme application through `acme.inline`;
2. executes the exact Contoso compatibility application through
   `contoso.inline`;
3. compares the exact capability events and artifacts after routing projection;
4. constructs both runtime clients from selected provider bindings and compares
   their normal and cancelled runtime lifecycle shapes;
5. proves missing-service and crossed-runtime rejection before implementation
   or runtime invocation;
6. checks stdout and stderr for input, environment, path, poison, and provider
   body sentinels.

The command runs only deterministic provider-free work. It does not execute
models, Docker, benchmarks, Prime, Native, DCI, promotion, or broad release
regression. Existing `make test.public-extension` and
`make test.cross-package-extension` remain separate earlier-layer gates.

## Compatibility Decision

W3b uses the existing `asterion.agent-runtime/v1`,
`asterion.capability/v1`, `asterion.capability-package/v1`, and
`asterion.application-assembly/v1` contracts unchanged. It adds one application
resource and provider-owned binding route inside an external fixture. Any
protocol limitation discovered during implementation is recorded for W4 and is
not patched into a closed v1 contract.
