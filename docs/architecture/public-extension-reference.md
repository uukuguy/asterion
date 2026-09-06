# Public Extension Reference Boundary

> Status: proposed for W2 implementation. Protocol impact: none.

## Purpose

W2 proves that an independently built Python wheel can contribute a capability
package, an application, and a compatible runtime without editing Asterion
source. The installed `asterion` command must discover the wheel through entry
point metadata, load only the selected providers, compose exact versioned
references, and execute the application outside the repository source tree.

The reference extension is an authoring example and an executable integration
fixture. It uses only two stable imports:

```python
from asterion.capability_sdk import ...
from asterion.application_sdk import ...
```

Extension code must not import from `asterion.applications`,
`asterion.assembly`, `asterion.capabilities`, `asterion.capability_packages`,
`asterion.runner`, or `asterion.runtime`.

## Public Python Surface

`asterion.capability_sdk` remains the public package and implementation surface.
W2 adds `asterion.application_sdk` as the public application and runtime adapter
surface. The new facade re-exports the minimum immutable contracts required by
an external provider:

- `APPLICATION_PROVIDER_PROTOCOL`
- `InstalledApplication`
- `InstalledApplicationProvider`
- `CapabilityPackageRef`
- `RuntimeFactoryBinding`
- `RuntimeFactoryContext`
- `AgentRuntimeClient`
- `CancellationSignal`
- `RunEvent`
- `RunRequest`
- `RuntimeManifest`
- `parse_event_stream`
- `RuntimeFactoryError`

The facade does not expose composers, discovery functions, registries, runners,
host-service construction, product verification, or protocol validators.
It exposes the canonical complete-stream parser, but not the lower-level JSON
schema or mapping validators. Those remain framework responsibilities.
Re-exporting the existing values introduces no parallel composer or runtime
implementation.

Before exposing these values, W2 hardens their Python value semantics without
changing their JSON v1 representation. `RuntimeManifest` and `RunRequest`
snapshot and validate constructor inputs. `RunEvent` deep-freezes its payload,
validates that the individual event is representable, and returns a fresh
public mapping from `to_mapping`. Caller mutation after construction cannot
change any exported value. Focused SDK tests cover direct construction,
`from_mapping`, nested payload mutation, and returned-mapping mutation.

## Extension Layout and Entry Points

The copyable reference remains under
`tests/fixtures/extensions/distribution/` and builds one wheel. Its wheel owns
all of the following resources:

```text
acme_sample_extension/
  __init__.py
  application.py
  capability.py
  poison.py
  runtime.py
asterion_capability_packages/acme.sample/1.0.0/payload/
  capability-package.json
  capabilities/research.json
  ...
asterion_capability_packages/acme.poison/1.0.0/payload/
  capability-package.json
  capabilities/poison-policy.json
asterion_applications/acme.sample/1.0.0/
  assembly.json
```

The wheel metadata declares its Asterion API dependency as
`asterion>=0.1.0,<0.2`. The isolated test still installs the two exact wheel
paths with `--no-deps`; it separately checks this declared compatibility range.

The wheel publishes exactly these entry points:

```toml
[project.entry-points."asterion.capability_packages"]
"acme.sample@1.0.0" = "acme_sample_extension.capability:create_package"
"acme.poison@1.0.0" = "acme_sample_extension.poison:create_poison_package"

[project.entry-points."asterion.applications"]
"acme-sample" = "acme_sample_extension.application:create_application_provider"
"acme-poison" = "acme_sample_extension.poison:create_poison_application_provider"

[project.entry-points."asterion.application_index"]
"acme.research-application__1.0.0" = "acme_sample_extension.application:create_application_provider"
```

The entries above are the wheel's complete entry-point set. The poison
capability has a complete valid portable payload, so distribution metadata
discovery can open and validate its descriptor without importing Python code.
Importing its provider module through entry-point `load()`, or importing the
poison application provider, raises a sentinel exception. No poison
application-index entry is published. These entries prove that metadata
listing and exact selection never load an unselected provider.

Application and package identities are exact. The assembly references
`acme.sample@1.0.0`, `acme.research@1.0.0`, and the provider-owned runtime
`acme.inline`. The manifest carries compatibility only; executable paths and
factories remain Python entry-point code.

## Discovery, Selection, and Execution

Unscoped `asterion list` reads application entry-point metadata without
importing the extension. `asterion list --provider acme-sample` imports only
the selected application provider. `asterion run` then performs this closed
sequence:

1. load and validate the exact selected application provider;
2. discover package candidates as metadata without importing providers;
3. prepare the exact distribution payload and bind its digest;
4. load only `acme.sample@1.0.0` from the selected prepared source;
5. compose the exact assembly and retain its provider-owned runtime binding;
6. execute the capability through the shared runner;
7. project only immutable public result data to JSON.

The extension runtime is deterministic and provider-free. It implements the
existing `asterion.agent-runtime/v1` host contract and emits one run ID,
contiguous sequence numbers, `run.started`, one `text.delta`, and one
`run.completed` terminal event. It reads no environment values, credentials,
files, network services, runtime options, or host services. The capability
invokes that runtime, calls
`parse_event_stream(event.to_mapping() for event in events)`, and only then
projects the event and artifact types declared by its capability manifest.

## Isolation Evidence

`make test.public-extension` is the single W2 acceptance command. Its test:

1. builds the Asterion core wheel and the extension wheel;
2. creates a clean virtual environment outside the repository tree;
3. installs both wheels without resolving undeclared product dependencies;
4. runs the installed console script with a working directory outside the
   repository and without adding repository paths to `PYTHONPATH`;
5. inspects extension wheel metadata for `asterion>=0.1.0,<0.2`, checks
   `application_sdk.__all__` exactly, and parses every extension `.py` file to
   permit only the standard library, its own package, `asterion.capability_sdk`,
   and `asterion.application_sdk` imports;
6. checks that unscoped listing imports no provider, selected provider listing
   imports no capability provider, and application-index selection maps to the
   exact application entry point; poison providers must remain unloaded;
7. runs this exact application selector:

```bash
asterion run \
  --provider acme-sample \
  --application acme.research-application@1.0.0 \
  --runtime acme.inline \
  --run-id acme-reference-run \
  --input private-input-sentinel
```

The test asserts the exact public application, runtime, run, event, and artifact
identities. Private sentinels placed in the environment and input must not
appear in stdout or stderr. The poison import sentinel must also remain absent.
Failure output remains the fixed CLI error.

The acceptance test covers only the necessary author path and boundary
assertions. It does not run product suites, Docker, model providers, benchmarks,
promotion checks, or broad release regression.

## Compatibility Decision

W2 changes no JSON schema and no closed v1 protocol. The application SDK is a
Python compatibility facade over existing contracts. Any limitation discovered
while implementing this reference is recorded for W4; it must not be worked
around by adding fields to an existing v1 manifest or by moving authority into
extension metadata.
