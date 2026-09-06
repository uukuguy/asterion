# Framework Public Inventory

> Recorded: 2026-09-06. This is a metadata-only inventory of the public
> framework surfaces visible in the repository. It is an evidence boundary,
> not a claim that every listed route has completed end-to-end verification.

## Application provider entry points

The application entry point group is `asterion.applications` in
`pyproject.toml`. Each entry point loads a provider only after a selected
application is requested.

| Provider entry point | Provider factory | Application IDs and version | Capability package refs | Declared runtime IDs |
|---|---|---|---|---|
| `controlled-code` | `asterion.applications.controlled_code:create_provider` | `code.quality@1.0.0` | `controlled-code@1.0.0` | `pi.reference` |
| `dci-agent-lite` | `asterion.applications.dci_agent_lite:create_provider` | `dci.research-capability@1.0.0`; `dci.complete-application@1.0.0`; `dci.local-benchmark-application@1.0.0` | `dci@1.0.0` | `claude-code.reference`, `pi.reference` |
| `prime-agent` | `asterion.applications.prime_agent.provider:create_provider` | `prime.arc-agi-3@1.0.0`; `prime.bounded-autonomy@1.0.0`; `prime.capability-program@1.0.0`; `prime.continual-improvement@1.0.0`; `prime.ipython-coding@1.0.0`; `prime.long-session-continuity@1.0.0`; `prime.programmatic-long-context@1.0.0`; `prime.recursive-workflow@1.0.0` | `prime-agent@1.0.0` | `prime.agent` |

The application index group `asterion.application_index` repeats these
selected application IDs as metadata-only aliases to the same factories.
Assembly file paths are provider-owned resources and are deliberately omitted
here when they would add implementation detail without changing the public
identity inventory.

## Capability packages and refs

The built-in package catalog currently declares these exact package refs:

| Package ref | Public package declaration |
|---|---|
| `controlled-code@1.0.0` | `src/asterion/capabilities/controlled_code/capability-package.json` |
| `dci@1.0.0` | `src/asterion/capabilities/dci/payload/capability-package.json` |
| `prime-agent@1.0.0` | `src/asterion/capabilities/prime_agent/payload/capability-package.json` |

The refs above are the exact refs used by the application providers. The
package manifests describe compatibility and package contents; they do not
authorize execution or carry prompts, credentials, commands, executable paths,
environment values, or mutable state.

## AgentRuntime IDs and registration sources

| Runtime ID | Registration source | Current application declarations |
|---|---|---|
| `pi.reference` | `asterion.runtime.defaults.default_runtime_factory_registry()` → `_create_pi_runtime` | `controlled-code`; all DCI applications |
| `claude-code.reference` | `asterion.runtime.defaults.default_runtime_factory_registry()` → `_create_claude_code_runtime` | all DCI applications |
| `prime.agent` | `asterion.runtime.defaults.default_runtime_factory_registry()` → `_create_prime_agent_runtime` | all Prime applications |

The registry is host-owned and selects exact runtime IDs. Runtime IDs are
metadata identities; runtime construction still requires the selected
application, resolved assembly, and the host services/options required by that
factory.

## Control providers

Control providers are listed separately from AgentRuntime registrations. They
implement control-plane contracts and do not, by their existence, add an
application route or an AgentRuntime ID.

| Control provider | Control-plane ID/version | Registration source | Public resource |
|---|---|---|---|
| Prime | `prime.gateway@0.1.0` | `asterion.control.providers.prime.factory.prime_control_plane_binding()` | `src/asterion/control/providers/prime/resources/control-plane.json` |
| Native | `asterion.native@0.1.0` | `asterion.control.providers.native.factory.native_control_plane_binding()` | `src/asterion/control/providers/native/resources/control-plane.json` |

Current fact: Prime is an `AgentRuntime`/application route through
`prime.agent` and the `prime-agent` application provider. Native is currently
only the `asterion.native` control provider. The expected Native AgentRuntime
and corresponding application route have not been implemented.

## Evidence boundary

This inventory establishes only repository-declared metadata and exact code
bindings. It does not establish that a provider is available in an installed
wheel, that a runtime executable or sidecar is present, that host services pass
preflight, or that a model/backend is reachable. It also does not promote
bounded product receipts or control-provider parity tests to framework
cross-package or cross-runtime completion.

No credentials, private roots, prompts, provider payloads, corpus text, raw
runtime output, or private paths are recorded here. `list`, `describe`,
`acceptance`, `make test`, and `make check` remain provider-free boundaries;
provider-backed or full benchmark execution requires its own bounded evidence.

## Reproduction record

Recorded on 2026-09-06 using read-only metadata/code inspection commands from
the repository root:

```text
rg --files -g 'docs/status/**' -g 'pyproject.toml' -g '*.py' -g '*.json'
rg -n 'asterion\.applications|asterion\.application_index' pyproject.toml
sed -n '1,180p' src/asterion/applications/{controlled_code,dci_agent_lite,prime_agent}/provider.py
sed -n '1,120p' src/asterion/runtime/defaults.py
rg -n 'CapabilityPackageRef\(' src/asterion
sed -n '1,180p' src/asterion/control/providers/{native,prime}/factory.py
sed -n '1,80p' src/asterion/control/providers/{native,prime}/resources/control-plane.json
```

The command record is intentionally limited to metadata and source
declarations; no execution, provider loading, network access, or credential
inspection is part of this inventory.
