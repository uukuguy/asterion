# Runtime Provider Boundaries

Asterion separates framework-shipped runtime adapters, application-owned
runtime integration, and optional control-plane providers. Runtime selection
remains exact and occurs while composing one already selected application
provider.

## Registry ownership

`default_runtime_factory_registry()` contains only domain-neutral reference
adapters shipped by the framework. It must not import an application provider,
application ID, product profile, or product host-service type.

An `InstalledApplicationProvider` may publish a tuple of
`runtime_factory_bindings` in its Python provider value. The tuple defaults to
empty, is excluded from representation, and is not part of an application,
assembly, capability-package, or runtime manifest. A binding is valid only when
its runtime ID is declared by at least one application from that same provider.
The provider value is loaded only after exact provider selection, so bindings
from unselected providers are neither imported nor considered.

Provider validation snapshots the tuple and rejects invalid, duplicate, or
unused runtime IDs. Application composition derives a new effective registry
from the host-supplied base registry plus the selected provider's bindings.
`RuntimeFactoryRegistry.extend(bindings)` preserves the existing immutable
snapshot and fails closed on every duplicate runtime ID; providers cannot
override host bindings through precedence.

The former Prime Gateway compatibility code carried the `prime.agent` binding,
its application-to-profile table, and its exact host-service requirements. It
has been removed from the distribution; its evidence is historical and
non-native. The peer agent implementations are `asterion.prime` and
`asterion.native`; both consume the same Asterion framework contracts.
`asterion-prime` must remain detached from Prime Agent source and SDK code. P1
through P7 are applications of `asterion-prime`, not runtime identities or
agent implementations. The framework default registry has no Prime imports or
routes.

## Selection and execution

```text
select one application-provider entry point
  -> load and validate that provider value
  -> validate its provider-owned runtime bindings
  -> extend the host base registry without replacement or precedence
  -> resolve each assembly against one exact runtime manifest
  -> retain the exact binding on the composed installed assembly
  -> construct that runtime only after host-service preflight
  -> execute the resolved plan through AgentRuntimeClient
```

The provider binding is executable Python integration supplied by the selected
provider. Manifests remain compatibility data and contain no factory, command,
executable path, environment, credential, or host-service value. Metadata-only
provider listing continues to use the application index and does not load the
provider entry point.

Runtime construction must use the binding retained by the composed installed
assembly. It must not reselect the runtime ID from the original base registry.
A multi-application host may rebuild one effective registry from its already
selected providers during preflight to detect cross-provider conflicts, but it
must verify that the result agrees with every retained assembly binding before
execution.

## Agent runtime and control plane

`AgentRuntimeClient` and `ControlPlaneClient` are orthogonal contracts:

| Contract | Responsibility | Primary operation |
|---|---|---|
| `AgentRuntimeClient` | Execute one resolved application request and emit one validated runtime event stream | `run(RunRequest)` |
| `ControlPlaneClient` | Manage commands, turns, events, checkpoints, reconnect, and lifecycle for a long-running agent session | `send`, `events`, `close` |

A control plane may call an injected turn adapter or host an application action,
and an AgentRuntime adapter may use an external session service. Neither fact
makes one contract an implementation of the other. They use separate manifests,
factory registries, contexts, and lifecycle validation.

No Prime Agent runtime or control provider remains in the distribution. The
former `prime.agent` AgentRuntime integration and `prime.gateway` control
provider have been removed; `asterion.prime` is the formal native agent
runtime. Native currently supplies the `asterion.native` control provider.
Native must not be added to the runtime registry until a separate AgentRuntime
adapter, exact binding, compatible assembly, and application provider route
exist.

## Compatibility boundary

The provider binding tuple is a backward-compatible, process-local Python
integration field with an empty default. It does not change any closed v1 JSON
schema or wire value. Existing providers that rely only on host reference
runtimes remain unchanged. Existing hosts continue to inject a base registry;
composition adds bindings only from the already selected provider and rejects
ambiguity.
